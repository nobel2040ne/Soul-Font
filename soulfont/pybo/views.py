from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import FileResponse, Http404, JsonResponse
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from django.contrib.auth import authenticate, login, logout #type: ignore
from django.contrib.auth.forms import UserCreationForm #type: ignore
from django.contrib.auth.decorators import login_required #type: ignore
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import Count

from .models import Font, Like, UserData
from .forms import CustomUserCreationForm

import io, os, json, threading, shutil, subprocess, uuid, zipfile
from foundry.font_processor import (
    AUTO_BOLD_AMOUNT,
    AUTO_LIGHT_AMOUNT,
    FontStyleProcessor,
    make_weight_variant,
    prepare_trace_images,
    script_fit_scales,
)
from foundry.set_font_metadata import apply_metadata, ascii_postscript_name
from foundry.refine_metrics import adjust_font_geometry, measure_fit, refine_metrics
from foundry.glyph_vectorizer import build_ttf

DEFAULT_FONT_NAME = "My Handwriting"  # default family name until the user renames it
FULL_CHARSET = os.path.join(settings.BASE_DIR, 'data', 'charset', 'korean11172.txt')

DEFAULT_TTF = 'ttf_files/MaruBuri-Regular.ttf'  # placeholder until a font is generated

def desktop(request):
    """The Finder. Applications live in a disk window you open them from, which is what the"""
    return render(request, 'pybo/desktop.html', {
        'font_count': (UserData.objects.exclude(ttf_file=DEFAULT_TTF)
                       .exclude(ttf_file='').count()),
        'my_count': (UserData.objects.filter(user=request.user).count()
                     if request.user.is_authenticated else 0),
    })

@ensure_csrf_cookie
def index(request):
    """The gallery, and on a phone the feed."""
    users = (UserData.objects.select_related('user')
             .exclude(ttf_file=DEFAULT_TTF)
             .exclude(ttf_file='')
             .annotate(like_count=Count('likes'))
             .order_by('-created_at', '-id'))
    liked = set()
    if request.user.is_authenticated:
        liked = set(Like.objects.filter(user=request.user).values_list('font_id', flat=True))
    fonts = Font.objects.all()
    return render(request, 'pybo/index.html',
                  {'fonts': fonts, 'users': users, 'liked': liked})

def signup_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('index')
    else:
        form = CustomUserCreationForm()
    return render(request, 'pybo/signup.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('index')
        else:
            return render(request, 'pybo/login.html', {'error': 'Invalid credentials'})
    else:
        return render(request, 'pybo/login.html')

def pw_reset_view(request):
    return render(request, 'pybo/pw_reset.html')

def logout_view(request):
    logout(request)
    return redirect('login')

def admin_page(request):
    return redirect('admin:index')

@login_required
def my_page(request):
    """The signed-in user's own fonts, as a list."""
    users = (request.user.fonts.select_related('user')
             .annotate(like_count=Count('likes'))
             .order_by('-created_at', '-id'))
    if not users.exists():
        return redirect('create_font')
    liked = set(Like.objects.filter(user=request.user).values_list('font_id', flat=True))
    return render(request, 'pybo/index.html',
                  {'fonts': Font.objects.all(), 'users': users, 'liked': liked,
                   'page_name': 'My Fonts'})

@login_required
def user_page(request, font_id):
    user_data = get_object_or_404(UserData.objects.select_related('user'), id=font_id)
    is_owner = request.user.id == user_data.user_id

    if request.method == 'POST' and is_owner and 'save_metadata' in request.POST:
        save_font_metadata(user_data, request.POST)

        if 'quote' in request.POST:
            user_data.quote = request.POST.get('quote', '').strip()

        if request.POST.get('remove_profile_image') and user_data.profile_image:
            user_data.profile_image.delete(save=False)
            user_data.profile_image = None

        picture = request.FILES.get('profile_image')
        if picture:
            if user_data.profile_image:
                user_data.profile_image.delete(save=False)
            user_data.profile_image = picture

        user_data.save()
        restamp_font_files(user_data)
        return redirect('user_page', font_id=user_data.id)

    user_fonts = user_data.user.fonts.order_by('-created_at', '-id')
    context = {
        'user_data': user_data,
        'profile_user': user_data.user,
        'is_owner': is_owner,
        'user_fonts': user_fonts,
        'font_name': user_data.font_name,
        'profile_image': user_data.profile_image,
        'ttf_file': user_data.ttf_file,
        'ttf_file_light': user_data.ttf_file_light,
        'ttf_file_bold': user_data.ttf_file_bold,
        'quote': user_data.quote,
    }
    return render(request, 'pybo/user_page.html', context)

def create_font(request):
    suggested = DEFAULT_FONT_NAME
    if request.user.is_authenticated:
        taken = set(request.user.fonts.values_list('font_name', flat=True))
        if suggested in taken:
            n = 2
            while f'{suggested} {n}' in taken:
                n += 1
            suggested = f'{suggested} {n}'
    return render(request, 'pybo/create_font.html', {'suggested_name': suggested})

def _clamp_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default

def _clamp_float(value, default, low, high):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default

def _has_pngs(path):
    return os.path.isdir(path) and any(f.lower().endswith('.png') for f in os.listdir(path))

def _vectorize(glyph_dir, out_path, font_basename, font_id):
    """Trace a directory of glyph PNGs into a TTF at out_path."""
    if os.environ.get('SOULFONT_VECTORIZER', '').lower() != 'imagetracer':
        return build_ttf(glyph_dir, out_path, font_basename,
                         fit_scales=script_fit_scales(glyph_dir))

    generate_ttf_js = os.path.join(settings.BASE_DIR, 'foundry', 'generateTTF.js')
    subprocess.run(
        ['node', generate_ttf_js, str(font_id), os.path.basename(glyph_dir), font_basename],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    src = os.path.join(settings.BASE_DIR, 'workdir', 'fonts', str(font_id), 'ttf_fonts',
                       f'{font_basename}.ttf')
    if not os.path.exists(src):
        raise FileNotFoundError(f'TTF generation failed: {src} does not exist.')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    shutil.move(src, out_path)
    return out_path

FIT_FILE = 'glyph_fit.json'

def _save_fit(user_font_dir, fit):
    try:
        os.makedirs(user_font_dir, exist_ok=True)
        with open(os.path.join(user_font_dir, FIT_FILE), 'w') as f:
            json.dump(fit, f)
    except Exception as e:
        print(f"[WARN] could not save glyph fit: {e}")

def _load_fit(user_font_dir):
    try:
        with open(os.path.join(user_font_dir, FIT_FILE)) as f:
            fit = json.load(f)
        return fit if {'hangul', 'latin'} <= set(fit) else None
    except Exception:
        return None

def letter(request):
    users = (UserData.objects.select_related('user')
             .exclude(ttf_file=DEFAULT_TTF)
             .exclude(ttf_file='')
             .order_by('-created_at', '-id'))
    return render(request, 'pybo/letter.html', {'users': users})

def about(request):
    return render(request, 'pybo/about.html')

def download_template(request):
    file_path = os.path.join(settings.STATICFILES_DIRS[0], 'templates', 'soulfont_template.pdf')
    return FileResponse(open(file_path, 'rb'), as_attachment=True,
                        filename='soulfont_template.pdf')

METADATA_FIELDS = ('author', 'copyright', 'license_text', 'license_url', 'description')

def save_font_metadata(user_data, post):
    """Copy the metadata fields off a POST onto the row. Returns True if anything changed."""
    before = {f: getattr(user_data, f) for f in METADATA_FIELDS}
    for f in METADATA_FIELDS:
        if f in post:
            setattr(user_data, f, post.get(f, '').strip())
    if 'version' in post:
        user_data.version = post.get('version', '').strip() or '1.000'
    if 'font_name' in post:
        name = post.get('font_name', '').strip()
        if name:
            user_data.font_name = name
    return any(getattr(user_data, f) != before[f] for f in METADATA_FIELDS)

def restamp_font_files(user_data):
    """Write the row's metadata into every weight on disk."""
    if not user_data.font_name or not user_data.ttf_file:
        return
    if user_data.ttf_file.name == DEFAULT_TTF:
        return
    meta = dict(
        user_id=str(user_data.user_id),
        designer=user_data.author,
        copyright=user_data.copyright,
        license_text=user_data.license_text,
        license_url=user_data.license_url,
        description=user_data.description,
        version=user_data.version,
    )
    targets = [(user_data.ttf_file, 'Regular')]
    if user_data.ttf_file_light:
        targets.append((user_data.ttf_file_light, 'Light'))
    if user_data.ttf_file_bold:
        targets.append((user_data.ttf_file_bold, 'Bold'))
    for field, weight in targets:
        try:
            apply_metadata(field.path, user_data.font_name, weight=weight, **meta)
        except Exception as e:
            print(f"[WARN] failed to update {weight} font metadata: {e}")

def font_status(request, font_id):
    """Progress for the polling UI. Cheap on purpose — it is hit every few seconds."""
    f = get_object_or_404(UserData, id=font_id)
    return JsonResponse({
        'status': f.status,
        'stage': f.status_stage,
        'percent': f.status_percent,
        'error': f.status_error,
        'ttf_url': f.ttf_file.url if f.is_ready else '',
    })

@login_required
@require_POST
def toggle_like(request, font_id):
    """Like or unlike, and report where that leaves things."""
    font = get_object_or_404(UserData, id=font_id)
    like, created = Like.objects.get_or_create(font=font, user=request.user)
    if not created:
        like.delete()
    return JsonResponse({'liked': created, 'count': font.likes.count()})

def download_font(request, font_id):
    """Serve the whole family as one zip."""
    user_data = get_object_or_404(UserData, id=font_id)
    weights = [(user_data.ttf_file, 'Regular'),
               (user_data.ttf_file_light, 'Light'),
               (user_data.ttf_file_bold, 'Bold')]

    family = ascii_postscript_name(user_data.font_name, str(user_data.id))
    buf = io.BytesIO()
    packed = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for field, weight in weights:
            if not field:
                continue
            try:
                with open(field.path, 'rb') as fh:
                    zf.writestr(f'{family}-{weight}.ttf', fh.read())
                packed += 1
            except OSError as e:
                print(f"[WARN] font {font_id}: {weight} missing from download ({e})")
        if packed:
            zf.writestr('README.txt', _family_readme(user_data, family, packed))

    if not packed:
        raise Http404('This font has no generated files yet.')

    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f'{family}.zip',
                        content_type='application/zip')

def _family_readme(user_data, family, weight_count):
    """Install notes + whatever metadata the owner filled in, shipped inside the zip."""
    lines = [
        f'{user_data.font_name}',
        '=' * len(user_data.font_name),
        '',
    ]
    if weight_count > 1:
        lines += [
            'Install every .ttf in this folder. They are one family: your editor will',
            f'show a single font named "{user_data.font_name}" with selectable weights',
            'rather than one entry per file.',
        ]
    else:
        lines.append(f'Install the .ttf in this folder to add "{user_data.font_name}".')
    lines += [
        '',
        '  macOS    select all, open, then Install Font',
        '  Windows  select all, right-click, then Install for all users',
        '',
    ]
    for label, value in (('Author', user_data.author),
                         ('Version', user_data.version),
                         ('License', user_data.license_text),
                         ('License URL', user_data.license_url),
                         ('Copyright', user_data.copyright),
                         ('Description', user_data.description)):
        if value:
            lines.append(f'{label + ":":14s}{value}')
    lines += ['', f'PostScript family: {family}', 'Made with Soul Font.', '']
    return '\n'.join(lines)

UPLOAD_FOLDER = os.path.join(settings.BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

TEMP_UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

TTF_OUTPUT_DIR = os.path.join(settings.MEDIA_ROOT, 'ttf_files')
os.makedirs(TTF_OUTPUT_DIR, exist_ok=True)

def _set_status(font_id, stage=None, percent=None, status=None, error=None):
    """Record pipeline progress for the polling endpoint."""
    fields = {}
    if stage is not None:
        fields['status_stage'] = stage
    if percent is not None:
        fields['status_percent'] = percent
    if status is not None:
        fields['status'] = status
    if error is not None:
        fields['status_error'] = error
    if fields:
        UserData.objects.filter(id=font_id).update(**fields)

STAGES = {
    'start':    ('Reading your template', 0),
    'generate': ('Generating glyphs', 2),
    'prepare':  ('Cleaning up the strokes', 18),
    'regular':  ('Building Regular', 61),
    'light':    ('Building Light', 74),
    'bold':     ('Building Bold', 86),
}

def _dir_size(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total

def _prune_build_files(font_id, user_font_dir, trace_source_name):
    """Delete the working files once the font itself is safely on disk."""
    style_id = f'user_{font_id}'
    workdir = os.path.join(settings.BASE_DIR, 'workdir')
    keep = {trace_source_name, FIT_FILE}

    doomed = [
        os.path.join(workdir, 'crops', style_id),
        os.path.join(workdir, 'glyphs', style_id),
        os.path.join(workdir, 'configs', f'{style_id}.yaml'),
    ]
    if os.path.isdir(user_font_dir):
        doomed += [os.path.join(user_font_dir, name)
                   for name in os.listdir(user_font_dir) if name not in keep]

    freed = 0
    for path in doomed:
        try:
            if os.path.isdir(path):
                freed += _dir_size(path)
                shutil.rmtree(path)
            elif os.path.isfile(path):
                freed += os.path.getsize(path)
                os.remove(path)
        except OSError as e:
            print(f"[WARN] font_id={font_id} could not remove {path}: {e}")

    print(f"[DONE] font_id={font_id} pruned {freed / 1e6:.0f} MB of build files "
          f"(kept {trace_source_name}/ and {FIT_FILE})")
    return freed

def _background_pipeline(template_pdf_path, font_id, charset_path=FULL_CHARSET, device_name='auto'):
    style_id = f"user_{font_id}"
    user_font_dir = os.path.join(settings.BASE_DIR, 'workdir', 'fonts', str(font_id))

    try:
        _set_status(font_id, *STAGES['start'], status=UserData.STATUS_RUNNING, error='')
        user_pdf_path = os.path.join(UPLOAD_FOLDER, f"{style_id}.pdf")
        shutil.copyfile(template_pdf_path, user_pdf_path)

        print(f"[DEBUG] Starting FontStyleProcessor (charset={charset_path}, device={device_name})...")
        _set_status(font_id, *STAGES['generate'])
        proc = FontStyleProcessor(user_pdf_path, charset_path=charset_path, device_name=device_name)
        proc.run_all()
        print("[DEBUG] FontStyleProcessor finished")

        inferred_src_dir = proc.save_dir
        flipped_result_dir = os.path.join(user_font_dir, 'flipped_result')
        if os.path.isdir(flipped_result_dir):
            shutil.rmtree(flipped_result_dir)
        os.makedirs(flipped_result_dir, exist_ok=True)

        for fname in os.listdir(inferred_src_dir):
            if fname.startswith("inferred_") and fname.endswith(".png"):
                shutil.copyfile(
                    os.path.join(inferred_src_dir, fname),
                    os.path.join(flipped_result_dir, fname)
                )
        print(f"[DEBUG] Copied inferred images to {flipped_result_dir}")

        trace_input_dir_name = 'trace_regular'
        trace_regular_dir = os.path.join(user_font_dir, trace_input_dir_name)
        try:
            _set_status(font_id, *STAGES['prepare'])
            prepare_trace_images(flipped_result_dir, trace_regular_dir)
            print(f"[DEBUG] Prepared high-resolution trace images for {trace_input_dir_name}")
        except Exception as e:
            trace_input_dir_name = 'flipped_result'
            trace_regular_dir = flipped_result_dir
            print(f"[WARN] trace image prep skipped, using raw glyphs: {e}")

        shared_fit = {}

        def build_weight(input_dir_name, font_basename, weight_label):
            final_name = f'{font_basename}.ttf'
            final_path = os.path.join(TTF_OUTPUT_DIR, final_name)
            _vectorize(os.path.join(user_font_dir, input_dir_name), final_path,
                       font_basename, font_id)
            try:
                if not shared_fit:
                    shared_fit.update(measure_fit(final_path))
                    _save_fit(user_font_dir, shared_fit)
                refine_metrics(final_path, fit=shared_fit)
            except Exception as e:
                print(f"[WARN] metrics refine skipped for {final_name}: {e}")
            apply_metadata(final_path, DEFAULT_FONT_NAME, user_id=str(font_id),
                           weight=weight_label)
            return final_name

        _set_status(font_id, *STAGES['regular'])
        reg_name = build_weight(trace_input_dir_name, f'user_font_{font_id}', 'Regular')
        user_data = UserData.objects.get(id=font_id)
        user_data.ttf_file.name = os.path.join('ttf_files', reg_name)
        user_data.ttf_file_light = None
        user_data.ttf_file_bold = None
        user_data.save(update_fields=['ttf_file', 'ttf_file_light', 'ttf_file_bold'])
        print(f"[DONE] font_id={font_id} Regular TTF generated -> {reg_name}")

        try:
            _set_status(font_id, *STAGES['light'])
            light_dir = os.path.join(user_font_dir, 'trace_light')
            make_weight_variant(trace_regular_dir, light_dir, weight='light',
                                amount=AUTO_LIGHT_AMOUNT)
            light_name = build_weight('trace_light', f'user_font_{font_id}_Light', 'Light')
            user_data.ttf_file_light.name = os.path.join('ttf_files', light_name)
            user_data.save(update_fields=['ttf_file_light'])
            print(f"[DONE] font_id={font_id} Light generated -> {light_name}")
        except Exception as e:
            print(f"[WARN] font_id={font_id} Light weight generation skipped: {e}")

        try:
            _set_status(font_id, *STAGES['bold'])
            bold_dir = os.path.join(user_font_dir, 'trace_bold')
            make_weight_variant(trace_regular_dir, bold_dir, weight='bold',
                                amount=AUTO_BOLD_AMOUNT)
            bold_name = build_weight('trace_bold', f'user_font_{font_id}_Bold', 'Bold')
            user_data.ttf_file_bold.name = os.path.join('ttf_files', bold_name)
            user_data.save(update_fields=['ttf_file_bold'])
            print(f"[DONE] font_id={font_id} Bold generated -> {bold_name}")
        except Exception as e:
            print(f"[WARN] font_id={font_id} Bold weight generation skipped: {e}")

        _set_status(font_id, 'Done', 100, status=UserData.STATUS_DONE)

        try:
            _prune_build_files(font_id, user_font_dir, trace_input_dir_name)
        except Exception as e:
            print(f"[WARN] font_id={font_id} could not prune build files: {e}")

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] font_id={font_id} generateTTF.js failed: {e.stderr}")
        _set_status(font_id, status=UserData.STATUS_FAILED,
                    error='Vectorizing failed. Please try generating again.')

    except Exception as e:
        print(f"[ERROR] font_id={font_id} pipeline failed: {e}")
        _set_status(font_id, status=UserData.STATUS_FAILED, error=str(e)[:500])

@login_required
def learning(request):
    if request.method == 'POST' and 'template' in request.FILES:

        for f in os.listdir(TEMP_UPLOAD_DIR):
            try:
                os.remove(os.path.join(TEMP_UPLOAD_DIR, f))
            except Exception:
                pass

        fs = FileSystemStorage(location=TEMP_UPLOAD_DIR)
        saved_name = fs.save(request.FILES['template'].name, request.FILES['template'])
        full_template_path = os.path.join(TEMP_UPLOAD_DIR, saved_name)

        charset_path = FULL_CHARSET
        device_name = 'cpu' if request.POST.get('accelerator') == 'cpu' else 'auto'

        font_name = request.POST.get('font_name', '').strip() or DEFAULT_FONT_NAME
        font = UserData.objects.create(user=request.user, font_name=font_name,
                                       status=UserData.STATUS_PENDING,
                                       status_stage='Queued', status_percent=0)
        if not request.user.fonts.filter(show_on_home=True).exists():
            font.show_on_home = True
            font.save(update_fields=['show_on_home'])

        threading.Thread(
            target=_background_pipeline,
            args=(full_template_path, font.id, charset_path, device_name),
            daemon=True
        ).start()

        return redirect('user_page', font_id=font.id)

    return render(request, "pybo/create_font.html")
