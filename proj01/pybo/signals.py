# pybo/signals.py
from django.contrib.auth.models import User #type: ignore
from django.db.models.signals import post_save #type: ignore
from django.dispatch import receiver #type: ignore

from .models import UserData

@receiver(post_save, sender=User)
def create_user_data(sender, instance, created, **kwargs):
    if created:
        # 새로운 User가 생성될 때마다 UserData를 한 번만 생성
        UserData.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_data(sender, instance, **kwargs):
    # User 저장 시 연결된 UserData도 함께 저장
    if hasattr(instance, 'userdata'):
        instance.userdata.save()
