from django.shortcuts import render, redirect, get_object_or_404  # type: ignore
from django.http import FileResponse, JsonResponse  # type: ignore
from django.core.files.storage import FileSystemStorage  # type: ignore
from django.conf import settings  # type: ignore
from django.contrib.auth import authenticate, login, logout #type: ignore
from django.contrib.auth.forms import UserCreationForm #type: ignore
from django.contrib.auth.decorators import login_required #type: ignore

from .models import Font, UserData
from .forms import CustomUserCreationForm

import os, threading, shutil, subprocess, uuid
from font_processor import (
    FontStyleProcessor,
    DEFAULT_CHARSET,
    make_weight_variant,
    stabilize_strokes,
)
from set_font_metadata import apply_metadata
from refine_metrics import adjust_font_geometry, refine_metrics

DEFAULT_FONT_NAME = "My Handwriting"  # default family name until the user renames it
FULL_CHARSET = os.path.join(settings.BASE_DIR, 'data', 'charset', 'korean11172.txt')

DEFAULT_TTF = 'ttf_files/MaruBuri-Regular.ttf'  # placeholder until a font is generated

def index(request):
    # Home shows one card per generated font the owner has opted to display.
    users = (UserData.objects.select_related('user')
             .filter(show_on_home=True)
             .exclude(ttf_file=DEFAULT_TTF)
             .exclude(ttf_file='')
             .order_by('-created_at', '-id'))
    fonts = Font.objects.all()
    return render(request, 'pybo/index.html', {'fonts': fonts, 'users': users})

def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('index')
        else:
            print(form.errors)
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
    """Send the signed-in user to their most recent font, or to create one if they
    have none yet. The menubar 'My Page' link uses this since a user now owns many."""
    font = request.user.fonts.order_by('-created_at', '-id').first()
    if font is None:
        return redirect('create_font')
    return redirect('user_page', font_id=font.id)

@login_required
def user_page(request, font_id):
    user_data = get_object_or_404(UserData.objects.select_related('user'), id=font_id)
    is_owner = request.user.id == user_data.user_id

    # Owner picks this font as the single one shown on Home, clearing their others.
    if request.method == 'POST' and is_owner and 'set_home' in request.POST:
        user_data.user.fonts.update(show_on_home=False)
        user_data.user.fonts.filter(id=user_data.id).update(show_on_home=True)
        return redirect('user_page', font_id=user_data.id)

    templates = user_data.templates.all()[:3]
    # All of the owner's fonts, for the "your fonts" button row.
    user_fonts = user_data.user.fonts.order_by('-created_at', '-id')
    context = {
        'user_data': user_data,
        'profile_user': user_data.user,
        'is_owner': is_owner,
        'user_fonts': user_fonts,
        'font_name': user_data.font_name,
        'profile_image': user_data.profile_image,
        'templates': templates,
        'ttf_file': user_data.ttf_file,
        'ttf_file_light': user_data.ttf_file_light,
        'ttf_file_bold': user_data.ttf_file_bold,
        'quote': user_data.quote,
    }
    return render(request, 'pybo/user_page.html', context)

def create_font(request):
    return render(request, 'pybo/create_font.html')

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

@login_required
def font_editor(request, font_id):
    user_data = get_object_or_404(UserData, id=font_id)
    if request.user.id != user_data.user_id:
        return redirect('user_page', font_id=font_id)

    download_url = None
    message = ''
    error = ''

    if request.method == 'POST':
        stroke = _clamp_int(request.POST.get('stroke_adjust'), 0, -5, 5)
        letter_spacing = _clamp_int(request.POST.get('letter_spacing_units'), 0, -120, 360)
        glyph_scale = _clamp_float(request.POST.get('glyph_scale'), 1.0, 0.65, 1.35)

        try:
            user_font_dir = os.path.join(settings.BASE_DIR, 'FONT', str(font_id))
            raw_source_dir = os.path.join(user_font_dir, 'flipped_result')
            stable_source_dir = os.path.join(user_font_dir, 'flipped_result_stable')
            if not _has_pngs(stable_source_dir) and _has_pngs(raw_source_dir):
                try:
                    stabilize_strokes(raw_source_dir, stable_source_dir)
                except Exception as e:
                    print(f"[WARN] editor stroke stabilizer skipped: {e}")

            source_dir = stable_source_dir if _has_pngs(stable_source_dir) else raw_source_dir
            if not _has_pngs(source_dir):
                source_dir = os.path.join(settings.BASE_DIR, 'static', 'outputs', f'user_{font_id}')
            if not _has_pngs(source_dir):
                raise FileNotFoundError('No generated glyph PNG directory found. Generate the font first.')

            variant_id = uuid.uuid4().hex[:8]
            input_dir_name = f'editor_{variant_id}'
            variant_dir = os.path.join(settings.BASE_DIR, 'FONT', str(font_id), input_dir_name)
            if stroke < 0:
                make_weight_variant(source_dir, variant_dir, weight='light', amount=abs(stroke))
                weight_label = 'Light'
            elif stroke > 0:
                make_weight_variant(source_dir, variant_dir, weight='bold', amount=stroke)
                weight_label = 'Bold'
            else:
                make_weight_variant(source_dir, variant_dir, weight='regular', amount=0)
                weight_label = 'Regular'

            font_basename = f'user_font_{font_id}_Edited_{variant_id}'
            generate_ttf_js = os.path.join(settings.BASE_DIR, 'generateTTF.js')
            subprocess.run(
                ['node', generate_ttf_js, str(font_id), input_dir_name, font_basename],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
            )

            src = os.path.join(settings.BASE_DIR, 'FONT', str(font_id), 'ttf_fonts', f'{font_basename}.ttf')
            if not os.path.exists(src):
                raise FileNotFoundError(f'Edited TTF was not created: {src}')

            final_name = f'{font_basename}.ttf'
            final_path = os.path.join(TTF_OUTPUT_DIR, final_name)
            shutil.move(src, final_path)
            refine_metrics(final_path)
            adjust_font_geometry(final_path, letter_spacing=letter_spacing, glyph_scale=glyph_scale)
            apply_metadata(
                final_path,
                f'{user_data.font_name} Edited',
                user_id=str(font_id),
                designer=user_data.author,
                copyright=user_data.copyright,
                license_text=user_data.license_text,
                license_url=user_data.license_url,
                description=user_data.description,
                version=user_data.version,
                weight=weight_label,
            )
            download_url = os.path.join(settings.MEDIA_URL, 'ttf_files', final_name)
            message = f'Edited {weight_label} font exported.'
        except subprocess.CalledProcessError as e:
            error = e.stderr or str(e)
        except Exception as e:
            error = str(e)

    context = {
        'user_data': user_data,
        'profile_user': user_data.user,
        'font_name': user_data.font_name,
        'ttf_file': user_data.ttf_file,
        'ttf_file_light': user_data.ttf_file_light,
        'ttf_file_bold': user_data.ttf_file_bold,
        'download_url': download_url,
        'message': message,
        'error': error,
    }
    return render(request, 'pybo/font_editor.html', context)

def letter(request):
    # Letter composer: pick any generated font (sliding carousel), write a note,
    # choose a paper design, and export the result as a PNG (done client-side).
    # Only real generated fonts — skip the default-TTF placeholders.
    users = (UserData.objects.select_related('user')
             .exclude(ttf_file=DEFAULT_TTF)
             .exclude(ttf_file='')
             .order_by('-created_at', '-id'))
    return render(request, 'pybo/letter.html', {'users': users})

def about(request):
    return render(request, 'pybo/about.html')

@login_required
def result(request, font_id=None):
    # Edit one specific font. With no id we fall back to the user's most recent font,
    # creating an empty one only if they have none yet.
    if font_id is not None:
        user_data = get_object_or_404(UserData, id=font_id, user=request.user)
    else:
        user_data = request.user.fonts.order_by('-created_at', '-id').first()
        if user_data is None:
            user_data = UserData.objects.create(user=request.user)

    if request.method == 'POST':
        new_name = request.POST.get('font_name', '').strip()
        user_data.font_name = new_name
        user_data.quote = request.POST.get('quote', '').strip()
        user_data.author = request.POST.get('author', '').strip()
        user_data.copyright = request.POST.get('copyright', '').strip()
        user_data.license_text = request.POST.get('license_text', '').strip()
        user_data.license_url = request.POST.get('license_url', '').strip()
        user_data.description = request.POST.get('description', '').strip()
        user_data.version = request.POST.get('version', '').strip() or '1.000'

        if request.POST.get('remove_profile_image') and user_data.profile_image:
            user_data.profile_image.delete(save=False)
            user_data.profile_image = None

        profile_image = request.FILES.get('profile_image')
        if profile_image:
            if user_data.profile_image:
                user_data.profile_image.delete(save=False)
            user_data.profile_image = profile_image

        user_data.save()

        # Rewrite the shipped TTF's metadata (incl. the Korean family name) to what the
        # user entered, so the font carries it when installed — no manual FontForge step.
        if new_name and user_data.ttf_file:
            meta = dict(
                user_id=str(request.user.id),
                designer=user_data.author,
                copyright=user_data.copyright,
                license_text=user_data.license_text,
                license_url=user_data.license_url,
                description=user_data.description,
                version=user_data.version,
            )
            # Rewrite each weight's metadata so they keep the shared (renamed) family name.
            targets = [(user_data.ttf_file, 'Regular')]
            if user_data.ttf_file_light:
                targets.append((user_data.ttf_file_light, 'Light'))
            if user_data.ttf_file_bold:
                targets.append((user_data.ttf_file_bold, 'Bold'))
            for field, weight in targets:
                try:
                    apply_metadata(field.path, new_name, weight=weight, **meta)
                except Exception as e:
                    print(f"[WARN] failed to update {weight} font metadata: {e}")

        return redirect('user_page', font_id=user_data.id)

    context = {
        'user_data': user_data,
        'font_name': user_data.font_name,
        'quote': user_data.quote,
        'ttf_file': user_data.ttf_file,
        'ttf_file_light': user_data.ttf_file_light,
        'ttf_file_bold': user_data.ttf_file_bold,
        'fonts': Font.objects.all().order_by('-id')
    }

    return render(request, 'pybo/result.html', context)

def download_template(request):
    file_path = os.path.join(settings.STATICFILES_DIRS[0], 'templates', '28_template.pdf')
    return FileResponse(open(file_path, 'rb'), as_attachment=True, filename='28_template.pdf')

UPLOAD_FOLDER = os.path.join(settings.BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

TEMP_UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

TTF_OUTPUT_DIR = os.path.join(settings.MEDIA_ROOT, 'ttf_files')
os.makedirs(TTF_OUTPUT_DIR, exist_ok=True)

PE_SCRIPT = os.path.join(settings.BASE_DIR, 'generate.pe')

def _background_pipeline(template_pdf_path, font_id, charset_path=DEFAULT_CHARSET, device_name='cpu'):
    # Everything is keyed on the font's id (UserData.id), so a user's fonts never
    # collide on disk or overwrite each other's TTFs.
    style_id = f"user_{font_id}"
    user_font_dir = os.path.join(settings.BASE_DIR, 'FONT', str(font_id))

    try:
        user_pdf_path = os.path.join(UPLOAD_FOLDER, f"{style_id}.pdf")
        shutil.copyfile(template_pdf_path, user_pdf_path)

        print(f"[DEBUG] Starting FontStyleProcessor (charset={charset_path}, device={device_name})...")
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

        stable_result_dir = os.path.join(user_font_dir, 'flipped_result_stable')
        stable_input_dir_name = 'flipped_result_stable'
        try:
            stabilize_strokes(flipped_result_dir, stable_result_dir)
            print(f"[DEBUG] Stabilized glyph images to {stable_result_dir}")
        except Exception as e:
            stable_result_dir = flipped_result_dir
            stable_input_dir_name = 'flipped_result'
            print(f"[WARN] stroke stabilizer skipped, using raw glyphs: {e}")

        generate_ttf_js = os.path.join(settings.BASE_DIR, 'generateTTF.js')

        def build_weight(input_dir_name, font_basename, weight_label):
            subprocess.run(
                ['node', generate_ttf_js, str(font_id), input_dir_name, font_basename],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
            )
            src = os.path.join(user_font_dir, 'ttf_fonts', f'{font_basename}.ttf')
            if not os.path.exists(src):
                raise FileNotFoundError(f"TTF generation failed: {src} does not exist.")
            final_name = f'{font_basename}.ttf'
            final_path = os.path.join(TTF_OUTPUT_DIR, final_name)
            shutil.move(src, final_path)
            # Give the traced Latin/symbol glyphs real metrics (baseline + proportional
            # spacing). Best-effort: Korean is untouched and the font is already valid, so a
            # refine failure must never lose the font.
            try:
                refine_metrics(final_path)
            except Exception as e:
                print(f"[WARN] metrics refine skipped for {final_name}: {e}")
            apply_metadata(final_path, DEFAULT_FONT_NAME, user_id=str(font_id),
                           weight=weight_label)
            return final_name

        # 2) Regular TTF — the primary result. It is built from the stabilized trace
        #    input, while the raw generated PNGs remain available for comparison.
        reg_name = build_weight(stable_input_dir_name, f'user_font_{font_id}', 'Regular')
        user_data = UserData.objects.get(id=font_id)
        user_data.ttf_file.name = os.path.join('ttf_files', reg_name)
        user_data.ttf_file_light = None
        user_data.ttf_file_bold = None
        user_data.save()
        print(f"[DONE] font_id={font_id} Regular TTF generated -> {reg_name}")

        # 3) Synthetic Light weight — best effort. This uses the same source as Regular,
        #    then thins strokes before vector tracing and saves as a real 300-weight TTF.
        try:
            light_dir = os.path.join(user_font_dir, 'flipped_result_light')
            make_weight_variant(stable_result_dir, light_dir, weight='light')
            light_name = build_weight('flipped_result_light', f'user_font_{font_id}_Light', 'Light')
            user_data.ttf_file_light.name = os.path.join('ttf_files', light_name)
            user_data.save()
            print(f"[DONE] font_id={font_id} Light generated -> {light_name}")
        except Exception as e:
            print(f"[WARN] font_id={font_id} Light weight generation skipped: {e}")

        # 4) Synthetic Bold weight — best effort. A failure here must not lose the Regular
        #    font, so it's isolated and only saved on success.
        try:
            bold_dir = os.path.join(user_font_dir, 'flipped_result_bold')
            make_weight_variant(stable_result_dir, bold_dir, weight='bold')
            bold_name = build_weight('flipped_result_bold', f'user_font_{font_id}_Bold', 'Bold')
            user_data.ttf_file_bold.name = os.path.join('ttf_files', bold_name)
            user_data.save()
            print(f"[DONE] font_id={font_id} Bold generated -> {bold_name}")
        except Exception as e:
            print(f"[WARN] font_id={font_id} Bold weight generation skipped: {e}")

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] font_id={font_id} generateTTF.js failed: {e.stderr}")

    except Exception as e:
        print(f"[ERROR] font_id={font_id} pipeline failed: {e}")
        

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

        # Fast (~2,350 common Hangul) vs Full (11,172) generation.
        charset_path = FULL_CHARSET if request.POST.get('speed') == 'full' else DEFAULT_CHARSET
        device_name = 'mps' if request.POST.get('accelerator') == 'mps' else 'cpu'

        # Each upload starts a brand-new font for this user; the pipeline fills in the
        # TTF on this exact row, so a user's fonts never overwrite one another.
        font = UserData.objects.create(user=request.user, font_name=DEFAULT_FONT_NAME)
        # A user's first font becomes their Home font automatically; later ones don't.
        if not request.user.fonts.filter(show_on_home=True).exists():
            font.show_on_home = True
            font.save(update_fields=['show_on_home'])

        threading.Thread(
            target=_background_pipeline,
            args=(full_template_path, font.id, charset_path, device_name),
            daemon=True
        ).start()

        return render(request, "pybo/result.html", {
            "user_id": request.user.id,
            "user_data": font,
            "font_name": font.font_name,
            "quote": font.quote,
        })

    return render(request, "pybo/create.html")
