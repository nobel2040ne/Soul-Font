from django.shortcuts import render, redirect, get_object_or_404  # type: ignore
from django.http import FileResponse, JsonResponse  # type: ignore
from django.core.files.storage import FileSystemStorage  # type: ignore
from django.conf import settings  # type: ignore
from django.contrib.auth import authenticate, login, logout #type: ignore
from django.contrib.auth.forms import UserCreationForm #type: ignore
from django.contrib.auth.decorators import login_required #type: ignore

from .models import Font, UserData
from .forms import CustomUserCreationForm

import os, threading, shutil, subprocess
from font_processor import FontStyleProcessor

def index(request):
    users = UserData.objects.select_related('user').all()
    fonts = Font.objects.all()
    print("Fonts:", fonts)
    print(users)
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
            return redirect('index')  # 로그인 후 홈 페이지로 리디렉션
        else:
            # 로그인 실패 시 메시지 표시
            return render(request, 'pybo/login.html', {'error': 'Invalid credentials'})
    else:
        return render(request, 'pybo/login.html')

def pw_reset_view(request):
    return render(request, 'pybo/pw_reset.html')

def logout_view(request):
    logout(request)
    return redirect('login')  # 로그아웃 후 로그인 페이지로 리디렉션

@login_required
def admin_page(request):
    return render(request, 'pybo/index.html')

@login_required
def user_page(request, user_id):
    user_data = get_object_or_404(UserData, user__id=user_id)
    templates = user_data.templates.all()[:3]
    context = {
        'font_name': user_data.font_name,
        'templates': templates,
        'ttf_file': user_data.ttf_file,
        'quote': user_data.quote,
    }
    return render(request, 'pybo/user_page.html', context)

def create_font(request):
    return render(request, 'pybo/create_font.html')

@login_required
def result(request):
    user_data, _ = UserData.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_data.font_name = request.POST.get('font_name', '').strip()
        user_data.quote = request.POST.get('quote', '').strip()
        user_data.save()

        return redirect('user_page', user_id=request.user.id)

    context = {
        'font_name': user_data.font_name,
        'quote': user_data.quote,
        'ttf_file': user_data.ttf_file,
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

def _background_pipeline(template_pdf_path, user_id):
    style_id = f"user_{user_id}"
    
    # [추가됨] 사용자별 폰트 생성 임시 디렉토리 경로
    user_font_dir = os.path.join(settings.BASE_DIR, 'FONT', str(user_id))

    try:
        # 1) PDF 복사 및 inference
        user_pdf_path = os.path.join(UPLOAD_FOLDER, f"{style_id}.pdf")
        shutil.copyfile(template_pdf_path, user_pdf_path)

        print("[DEBUG] Starting FontStyleProcessor...")
        proc = FontStyleProcessor(user_pdf_path)
        proc.run_all()
        print("[DEBUG] FontStyleProcessor finished")

        # ==== 여기서 inference 이미지 복사 (경로 수정) ====
        inferred_src_dir = proc.save_dir
        
        # [수정됨] PNG 파일을 복사할 목적지를 사용자별 경로로 변경
        flipped_result_dir = os.path.join(user_font_dir, 'flipped_result')
        os.makedirs(flipped_result_dir, exist_ok=True) # FONT/<user_id>/flipped_result 디렉토리 생성

        for fname in os.listdir(inferred_src_dir):
            if fname.startswith("inferred_") and fname.endswith(".png"):
                shutil.copyfile(
                    os.path.join(inferred_src_dir, fname),
                    os.path.join(flipped_result_dir, fname)
                )
        print(f"[DEBUG] Copied inferred images to {flipped_result_dir}")

        # 2) TTF 생성 (Node.js generateTTF.js 호출)
        generate_ttf_js = os.path.join(settings.BASE_DIR, 'generateTTF.js')
        result = subprocess.run(
            ['node', generate_ttf_js, str(user_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        print(result.stdout)

        # 3) TTF 파일 경로 지정 및 이동 (경로 수정 및 최종 파일 사용)
        # [수정됨] 후처리된 최종 TTF 파일 경로를 사용합니다.
        src_ttf_path = os.path.join(
            user_font_dir, 'ttf_fonts', f'user_font_{user_id}.ttf' 
        )
        final_ttf_filename = f"user_font_{user_id}.ttf" # 실제 저장될 파일 이름
        final_ttf_path = os.path.join(TTF_OUTPUT_DIR, final_ttf_filename)

        if not os.path.exists(src_ttf_path):
            raise FileNotFoundError(f"TTF 파일 생성 실패: {src_ttf_path}가 존재하지 않습니다.")

        shutil.move(src_ttf_path, final_ttf_path)

        print(f"[DONE] user_id={user_id} TTF 생성 완료 → {final_ttf_path}")

        # 4) UserData 업데이트
        user_data, _ = UserData.objects.get_or_create(user_id=user_id)
        
        # FileField에 상대경로 저장
        user_data.ttf_file.name = os.path.join('ttf_files', final_ttf_filename)
        user_data.font_name = f"My Font"
        user_data.save()

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] user_id={user_id} generateTTF.js 실행 실패: {e.stderr}")

    except Exception as e:
        print(f"[ERROR] user_id={user_id} 파이프라인 실패: {e}")
        
    # finally:
    #     # [추가됨] 작업 완료 후 임시 파일/디렉토리 정리
    #     if os.path.exists(user_font_dir):
    #         try:
    #             shutil.rmtree(user_font_dir)
    #             print(f"[CLEANUP] 임시 디렉토리 삭제 완료: {user_font_dir}")
    #         except OSError as e:
    #             print(f"[ERROR] 임시 디렉토리 삭제 실패: {e.strerror}")

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

        threading.Thread(
            target=_background_pipeline,
            args=(full_template_path, request.user.id),
            daemon=True
        ).start()

        return render(request, "pybo/result.html", {"user_id": request.user.id})

    return render(request, "pybo/create.html")