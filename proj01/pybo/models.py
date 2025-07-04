from django.db import models #type: ignore
from django.contrib.auth.models import User #type: ignore

class Font(models.Model):
    text = models.CharField(max_length=255, default="No Description")
    font_description = models.TextField(null=True, blank=True)
    ttf_file = models.FileField(upload_to='fonts/')

    def __str__(self):
        return self.text
    
class UserData(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, default = None)
    font_name = models.CharField(max_length=100, default='기본폰트')
    
    template1 = models.ImageField(upload_to='templates/', null=True, blank=True)
    template2 = models.ImageField(upload_to='templates/', null=True, blank=True)
    template3 = models.ImageField(upload_to='templates/', null=True, blank=True)

    ttf_file = models.FileField(
      upload_to='ttf_files/',
      default='ttf_files/MaruBuri-Regular.ttf')
    quote = models.TextField()

    def __str__(self):
        return f"{self.user.username} – {self.font_name}"
    
class Template(models.Model):
    user = models.ForeignKey(UserData, on_delete=models.CASCADE, related_name='templates', null=True)
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to='templates/')

    def __str__(self):
        return self.name
