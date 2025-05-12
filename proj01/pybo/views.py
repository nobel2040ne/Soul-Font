import subprocess
from django.shortcuts import render, redirect, get_object_or_404  # type: ignore
from django.http import FileResponse, HttpResponse, Http404  # type: ignore
from django.core.files.storage import FileSystemStorage  # type: ignore
import os
from django.conf import settings  # type: ignore
from .forms import FontForm
from .models import Font, UserData
import uuid, shutil
from django.contrib.staticfiles import finders #type: ignore
from django.contrib.auth import authenticate, login, logout #type: ignore
from django.contrib.auth.forms import UserCreationForm #type: ignore
from django.contrib.auth.decorators import login_required #type: ignore
from .forms import CustomUserCreationForm

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
    # 템플릿 3개만 전달
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

# def learning(request):
    return render(request, 'pybo/learning.html')

@login_required
def result(request):
    user_data, _ = UserData.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_data.font_name = request.POST.get('font_name', '').strip()
        user_data.quote = request.POST.get('quote', '').strip()
        user_data.save()

        return redirect('user_page', user_id=request.user.id)

    # GET 요청 시 보여줄 내용 구성
    context = {
        'font_name': user_data.font_name,
        'quote': user_data.quote,
        'ttf_file': user_data.ttf_file,
        'fonts': Font.objects.all().order_by('-id')  # 혹시 사용 중이라면
    }

    return render(request, 'pybo/result.html', context)

def download_template1(request):
    file_path1 = os.path.join(settings.STATICFILES_DIRS[0], 'templates', '1-uniform.png')
    return FileResponse(open(file_path1, 'rb'), as_attachment=True, filename='1-uniform.png')

def download_template2(request):
    file_path2 = os.path.join(settings.STATICFILES_DIRS[0], 'templates', '2-uniform.png')
    return FileResponse(open(file_path2, 'rb'), as_attachment=True, filename='2-uniform.png')

def download_template3(request):
    file_path3 = os.path.join(settings.STATICFILES_DIRS[0], 'templates', '3-uniform.png')
    return FileResponse(open(file_path3, 'rb'), as_attachment=True, filename='3-uniform.png')

def run_handwriting_pipeline(template1_path, template2_path, template3_path, txt_file_path):

    # 3개의 이미지를 개별적으로 처리하는 명령어 수정
    crop_command1 = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "01_crop.py")}" --src_dir="{os.path.dirname(template1_path)}" --dst_dir="cropped_dir" --txt="{txt_file_path}"'
    subprocess.run(crop_command1, shell=True, check=True)

    crop_command2 = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "01_crop.py")}" --src_dir="{os.path.dirname(template2_path)}" --dst_dir="cropped_dir" --txt="{txt_file_path}"'
    subprocess.run(crop_command2, shell=True, check=True)

    crop_command3 = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "01_crop.py")}" --src_dir="{os.path.dirname(template3_path)}" --dst_dir="cropped_dir" --txt="{txt_file_path}"'
    subprocess.run(crop_command3, shell=True, check=True)

    # font2image
    font2image_command = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "02_font2image.py")}" --src_font="{os.path.join(settings.BASE_DIR, "pybo", "scripts", "NanumGothic.ttf")}" --dst_font="{os.path.join(settings.BASE_DIR, "pybo", "scripts", "NanumGothic.ttf")}" --sample_dir="pair_dir/" --handwriting_dir="cropped_dir/"'
    subprocess.run(font2image_command, shell=True, check=True)

    # 패키지 생성
    package_command = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "03_package.py")}" --dir="pair_dir/" --save_dir="package_dir"'
    subprocess.run(package_command, shell=True, check=True)

    # 첫 번째 학습
    train_command_1 = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "04_train.py")}" --experiment_dir="experiment/" --experiment_id=0 --batch_size=16 --lr=0.001 --epoch=60 --sample_steps=100 --schedule=20 --L1_penalty=100 --Lconst_penalty=15 --freeze_encoder=1'
    subprocess.run(train_command_1, shell=True, check=True)
    
    # 두 번째 학습
    train_command_2 = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "04_train.py")}" --experiment_dir="experiment/" --experiment_id=0 --batch_size=16 --lr=0.001 --epoch=120 --sample_steps=100 --schedule=40 --L1_penalty=500 --Lconst_penalty=1000 --freeze_encoder=1'
    subprocess.run(train_command_2, shell=True, check=True)

    # 추론
    infer_command = f'python "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "05_infer.py")}" --model_dir="experiment/checkpoint/experiment_0_batch_16" --batch_size=1 --source_obj="experiment/data/val.obj" --embedding_ids=0 --save_dir="experiment/inferred_result" --progress_file="experiment/logs/progress"'
    subprocess.run(infer_command, shell=True, check=True)

    # 경로 정의
    src = os.path.join(settings.BASE_DIR, "experiment", "inferred_result")
    dst = os.path.join(settings.BASE_DIR, "FONT", "inferred_result")

    # 이미 존재하는 대상 폴더가 있다면 삭제
    if os.path.exists(dst):
        shutil.rmtree(dst)

    # 결과 폴더 이동
    shutil.move(src, dst)

    # TTF 생성
    node_command = f'node "{os.path.join(settings.BASE_DIR, "pybo", "generateTTF.js")}"'
    subprocess.run(node_command, shell=True, check=True)

    return "Handwriting pipeline completed successfully"

@login_required
def learning(request):
    try:
        if request.method == 'POST' and all(f in request.FILES for f in ['template1', 'template2', 'template3']):
            # 업로드된 파일들 받기
            template1 = request.FILES['template1']
            template2 = request.FILES['template2']
            template3 = request.FILES['template3']

            # 임시 저장 디렉토리 설정
            temp_uploads_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
            os.makedirs(temp_uploads_dir, exist_ok=True)

            # 파일 저장
            fs = FileSystemStorage(location=temp_uploads_dir)
            template1_path = fs.save(template1.name, template1)
            template2_path = fs.save(template2.name, template2)
            template3_path = fs.save(template3.name, template3)

            full_template1_path = os.path.join(temp_uploads_dir, template1_path)
            full_template2_path = os.path.join(temp_uploads_dir, template2_path)
            full_template3_path = os.path.join(temp_uploads_dir, template3_path)

            # txt 파일 경로
            txt_file_path = os.path.join(settings.BASE_DIR, 'pybo', 'scripts', '399-uniform.txt')

            # 파이프라인 실행
            result = run_handwriting_pipeline(full_template1_path, full_template2_path, full_template3_path, txt_file_path)

            return HttpResponse(result)
        
        return HttpResponse("No files uploaded.", status=400)

    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status=500)
    # if request.method == 'POST' and request.FILES.get('template1') and request.FILES.get('template2') and request.FILES.get('template3'):
    #     # 업로드된 템플릿 파일들 받기
    #     template1 = request.FILES['template1']
    #     template2 = request.FILES['template2']
    #     template3 = request.FILES['template3']

    #     # 파일 저장 경로 지정
    #     temp_uploads_dir = os.path.join(settings.BASE_DIR, 'media', 'temp_uploads')
    #     os.makedirs(temp_uploads_dir, exist_ok=True)

    #     # 파일 경로 지정
    #     template1_path = os.path.join(temp_uploads_dir, template1.name)
    #     template2_path = os.path.join(temp_uploads_dir, template2.name)
    #     template3_path = os.path.join(temp_uploads_dir, template3.name)

    #     # 파일 저장
    #     fs = FileSystemStorage(location=temp_uploads_dir)
    #     fs.save(template1.name, template1)
    #     fs.save(template2.name, template2)
    #     fs.save(template3.name, template3)

    #     # pybo/scripts/에 있는 txt 파일 경로 설정
    #     txt_file_path = os.path.join(settings.BASE_DIR, 'pybo', 'scripts', '399-uniform.txt')

    #     # 파이프라인 실행
    #     result = run_handwriting_pipeline(template1_path, template2_path, template3_path, txt_file_path)

    #     return HttpResponse(result)

    # return HttpResponse("No files uploaded.")
