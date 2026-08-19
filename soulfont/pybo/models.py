from django.db import models #type: ignore
from django.contrib.auth.models import User #type: ignore

class Font(models.Model):
    text = models.CharField(max_length=255, default="No Description")
    font_description = models.TextField(null=True, blank=True)
    ttf_file = models.FileField(upload_to='fonts/')

    def __str__(self):
        return self.text

class UserData(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fonts', default=None)
    font_name = models.CharField(max_length=100, default='Default Font')
    profile_image = models.ImageField(upload_to='profiles/', null=True, blank=True)

    show_on_home = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    template1 = models.ImageField(upload_to='templates/', null=True, blank=True)
    template2 = models.ImageField(upload_to='templates/', null=True, blank=True)
    template3 = models.ImageField(upload_to='templates/', null=True, blank=True)

    ttf_file = models.FileField(
      upload_to='ttf_files/',
      default='ttf_files/MaruBuri-Regular.ttf')
    ttf_file_light = models.FileField(upload_to='ttf_files/', null=True, blank=True)
    ttf_file_bold = models.FileField(upload_to='ttf_files/', null=True, blank=True)
    quote = models.TextField()

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DONE)
    status_stage = models.CharField(max_length=60, blank=True, default='')
    status_percent = models.PositiveSmallIntegerField(default=0)
    status_error = models.TextField(blank=True, default='')

    @property
    def is_ready(self):
        """True when the font on disk is this user's own, not the bundled placeholder."""
        return self.status == self.STATUS_DONE and bool(self.ttf_file)

    @property
    def weight_count(self):
        """How many weights this font actually holds."""
        return sum(1 for f in (self.ttf_file, self.ttf_file_light, self.ttf_file_bold) if f)

    author = models.CharField(max_length=100, blank=True, default='')
    copyright = models.CharField(max_length=200, blank=True, default='')
    license_text = models.CharField(max_length=200, blank=True, default='')
    license_url = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    version = models.CharField(max_length=30, blank=True, default='1.000')

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.user.username} – {self.font_name}"

class Like(models.Model):
    """One person having liked one font."""
    font = models.ForeignKey(UserData, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='font_likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['font', 'user'], name='uniq_like_font_user'),
        ]

    def __str__(self):
        return f"{self.user.username} \u2661 {self.font.font_name}"

class FontExport(models.Model):
    """One run of the editor's "Export Adjusted Copy"."""
    font = models.ForeignKey(UserData, on_delete=models.CASCADE, related_name='exports')
    token = models.CharField(max_length=8, unique=True)

    stroke_adjust = models.SmallIntegerField(default=0)
    letter_spacing_units = models.SmallIntegerField(default=0)
    glyph_scale = models.FloatField(default=1.0)

    ttf_file = models.FileField(upload_to='ttf_files/', null=True, blank=True)

    STATUS_CHOICES = UserData.STATUS_CHOICES
    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=UserData.STATUS_PENDING)
    status_stage = models.CharField(max_length=60, blank=True, default='')
    status_percent = models.PositiveSmallIntegerField(default=0)
    status_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    @property
    def is_ready(self):
        return self.status == UserData.STATUS_DONE and bool(self.ttf_file)

    def __str__(self):
        return f"{self.font.font_name} export {self.token} ({self.status})"

class Template(models.Model):
    user = models.ForeignKey(UserData, on_delete=models.CASCADE, related_name='templates', null=True)
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to='templates/')

    def __str__(self):
        return self.name
