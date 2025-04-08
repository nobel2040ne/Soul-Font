# import subprocess
# from django.shortcuts import render, redirect
# from django.http import FileResponse, HttpResponse
# from django.core.files.storage import FileSystemStorage
# import os
# from django.conf import settings
# from .forms import FontForm
# from .models import Font
# import uuid, shutil

# def index(request):
#     fonts = Font.objects.all()
#     print("Fonts:", fonts)
#     return render(request, 'pybo/index.html', {'fonts': fonts})

# def create_font(request):
#     return render(request, 'pybo/create_font.html')

# def learning(request):
#     return render(request, 'pybo/learning.html')

# def result(request):
#     if request.method == 'POST':
#         form = FontForm(request.POST, request.FILES)
#     if form.is_valid():
#         font = form.save() # 데이터 저장
#         return redirect('result') # 저장 후 다시 result.html 렌더링
#     else:
#         form = FontForm()

#     fonts = Font.objects.all().order_by('-id') # 최신 폰트 먼저 보여주기
#     return render(request, 'pybo/result.html', {'form': form, 'fonts': fonts})

# def download_template1():
#     file_path1 = os.path.join(settings.STATICFILES_DIRS[0], 'templates/1-uniform.png')
#     return FileResponse(open(file_path1, 'rb'), as_attachment=True, filename='1-uniform.png')

# def download_template2():
#     file_path2 = os.path.join(settings.STATICFILES_DIRS[0], 'templates/2-uniform.png')
#     return FileResponse(open(file_path2, 'rb'), as_attachment=True, filename='2-uniform.png')

# def download_template3():
#     file_path3 = os.path.join(settings.STATICFILES_DIRS[0], 'templates/3-uniform.png')
#     return FileResponse(open(file_path3, 'rb'), as_attachment=True, filename='3-uniform.png')

# def run_handwriting_pipeline(template1_path, template2_path, template3_path, txt_file_path):

#     # 3개의 이미지를 개별적으로 처리하는 명령어 수정
#     crop_command1 = f"python C:/Users/nobel/start-django/proj01/pybo/scripts/01_crop.py --src_dir={os.path.dirname(template1_path)} --dst_dir=cropped_dir --txt={txt_file_path}"
#     subprocess.run(crop_command1, shell=True, check=True)

#     crop_command2 = f"python C:/Users/nobel/start-django/proj01/pybo/scripts/01_crop.py --src_dir={os.path.dirname(template2_path)} --dst_dir=cropped_dir --txt={txt_file_path}"
#     subprocess.run(crop_command2, shell=True, check=True)

#     crop_command3 = f"python C:/Users/nobel/start-django/proj01/pybo/scripts/01_crop.py --src_dir={os.path.dirname(template3_path)} --dst_dir=cropped_dir --txt={txt_file_path}"
#     subprocess.run(crop_command3, shell=True, check=True)

#     # font2image
#     font2image_command = f"python pybo/scripts/02_font2image.py --src_font=pybo/scripts/NanumGothic.ttf --dst_font=pybo/scripts/NanumGothic.ttf --sample_dir=pair_dir/ --handwriting_dir=cropped_dir/"
#     subprocess.run(font2image_command, shell=True, check=True)

#     # 패키지 생성
#     package_command = "python pybo/scripts/03_package.py --dir=pair_dir/ --save_dir=package_dir"
#     subprocess.run(package_command, shell=True, check=True)

#     # 첫 번째 학습
#     train_command_1 = "python pybo/scripts/04_train.py --experiment_dir=experiment/ --experiment_id=0 --batch_size=16 --lr=0.001 --epoch=60 --sample_steps=100 --schedule=20 --L1_penalty=100 --Lconst_penalty=15 --freeze_encoder=1"
#     subprocess.run(train_command_1, shell=True, check=True)

#     # 두 번째 학습
#     train_command_2 = "python pybo/scripts/04_train.py --experiment_dir=experiment/ --experiment_id=0 --batch_size=16 --lr=0.001 --epoch=120 --sample_steps=100 --schedule=40 --L1_penalty=500 --Lconst_penalty=1000 --freeze_encoder=1"
#     subprocess.run(train_command_2, shell=True, check=True)

#     # 추론
#     infer_command = "python pybo/scripts/05_infer.py --model_dir=experiment/checkpoint/experiment_0_batch_16 --batch_size=1 --source_obj=experiment/data/val.obj --embedding_ids=0 --save_dir=experiment/inferred_result --progress_file=experiment/logs/progress"
#     subprocess.run(infer_command, shell=True, check=True)

#     # 결과 폴더 이동
#     os.makedirs("FONT/inferred_result", exist_ok=True)
#     move_command = "mv experiment/inferred_result FONT/inferred_result"
#     subprocess.run(move_command, shell=True, check=True)

#     # TTF 생성
#     node_command = "node pybo/scripts/generateTTF.js"
#     subprocess.run(node_command, shell=True, check=True)

#     return "Handwriting pipeline completed successfully"

# def learning(request):
#     if request.method == 'POST' and request.FILES.get('template1') and request.FILES.get('template2') and request.FILES.get('template3'):
#         # 업로드된 템플릿 파일들 받기
#         template1 = request.FILES['template1']
#         template2 = request.FILES['template2']
#         template3 = request.FILES['template3']

#         # 파일 저장 경로 지정
#         temp_uploads_dir = os.path.join(settings.BASE_DIR, 'media', 'temp_uploads')
#         os.makedirs(temp_uploads_dir, exist_ok=True)

#         # 파일 경로 지정
#         template1_path = os.path.join(temp_uploads_dir, template1.name)
#         template2_path = os.path.join(temp_uploads_dir, template2.name)
#         template3_path = os.path.join(temp_uploads_dir, template3.name)

#         # 파일 저장
#         fs = FileSystemStorage(location=temp_uploads_dir)
#         fs.save(template1.name, template1)
#         fs.save(template2.name, template2)
#         fs.save(template3.name, template3)

#         # pybo/scripts/에 있는 txt 파일 경로 설정
#         txt_file_path = os.path.join(settings.BASE_DIR, 'pybo', 'scripts', '399-uniform.txt')

#         # 파이프라인 실행
#         result = run_handwriting_pipeline(template1_path, template2_path, template3_path, txt_file_path)

#         return HttpResponse(result)

#     return HttpResponse("No files uploaded.")

import subprocess
from django.shortcuts import render, redirect
from django.http import FileResponse, HttpResponse
from django.core.files.storage import FileSystemStorage
import os
from django.conf import settings
from .forms import FontForm
from .models import Font
import uuid, shutil

def index(request):
    fonts = Font.objects.all()
    print("Fonts:", fonts)
    return render(request, 'pybo/index.html', {'fonts': fonts})

def create_font(request):
    return render(request, 'pybo/create_font.html')

def learning(request):
    return render(request, 'pybo/learning.html')

def result(request):
    if request.method == 'POST':
        form = FontForm(request.POST, request.FILES)
        if form.is_valid():
            font = form.save()  # 데이터 저장
            return redirect('result')  # 저장 후 다시 result.html 렌더링
    else:
        form = FontForm()

    fonts = Font.objects.all().order_by('-id')  # 최신 폰트 먼저 보여주기
    return render(request, 'pybo/result.html', {'form': form, 'fonts': fonts})

def download_template1():
    file_path1 = os.path.join(settings.STATICFILES_DIRS[0], 'templates', '1-uniform.png')
    if not os.path.exists(file_path1):
        return HttpResponse("File not found", status=404)
    return FileResponse(open(file_path1, 'rb'), as_attachment=True, filename='1-uniform.png')

def download_template2():
    file_path2 = os.path.join(settings.STATICFILES_DIRS[0], 'templates', '2-uniform.png')
    return FileResponse(open(file_path2, 'rb'), as_attachment=True, filename='2-uniform.png')

def download_template3():
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

    # 결과 폴더 이동
    os.makedirs(os.path.join(settings.BASE_DIR, "FONT", "inferred_result"), exist_ok=True)
    move_command = f'move "{os.path.join(settings.BASE_DIR, "experiment", "inferred_result")}" "{os.path.join(settings.BASE_DIR, "FONT", "inferred_result")}"'
    subprocess.run(move_command, shell=True, check=True)

    # TTF 생성
    node_command = f'node "{os.path.join(settings.BASE_DIR, "pybo", "scripts", "generateTTF.js")}"'
    subprocess.run(node_command, shell=True, check=True)

    return "Handwriting pipeline completed successfully"

def learning(request):
    if request.method == 'POST' and request.FILES.get('template1') and request.FILES.get('template2') and request.FILES.get('template3'):
        # 업로드된 템플릿 파일들 받기
        template1 = request.FILES['template1']
        template2 = request.FILES['template2']
        template3 = request.FILES['template3']

        # 파일 저장 경로 지정
        temp_uploads_dir = os.path.join(settings.BASE_DIR, 'media', 'temp_uploads')
        os.makedirs(temp_uploads_dir, exist_ok=True)

        # 파일 경로 지정
        template1_path = os.path.join(temp_uploads_dir, template1.name)
        template2_path = os.path.join(temp_uploads_dir, template2.name)
        template3_path = os.path.join(temp_uploads_dir, template3.name)

        # 파일 저장
        fs = FileSystemStorage(location=temp_uploads_dir)
        fs.save(template1.name, template1)
        fs.save(template2.name, template2)
        fs.save(template3.name, template3)

        # pybo/scripts/에 있는 txt 파일 경로 설정
        txt_file_path = os.path.join(settings.BASE_DIR, 'pybo', 'scripts', '399-uniform.txt')

        # 파이프라인 실행
        result = run_handwriting_pipeline(template1_path, template2_path, template3_path, txt_file_path)

        return HttpResponse(result)

    return HttpResponse("No files uploaded.")
