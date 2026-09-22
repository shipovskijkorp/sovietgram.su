from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.urls import include, path

def _deny_private_message_media(request, path):
    raise Http404


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.messenger.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("media/messages/<path:path>", _deny_private_message_media),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
