from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.urls import include, path

from . import pwa

def _deny_private_media(request, path):
    raise Http404


urlpatterns = [
    path("manifest.webmanifest", pwa.manifest, name="pwa_manifest"),
    path("sw.js", pwa.service_worker, name="pwa_worker"),
    path("app-icon/<int:size>.png", pwa.icon, name="pwa_icon"),
    path("offline/", pwa.offline, name="pwa_offline"),
    path("admin/", admin.site.urls),
    path("control/", include("apps.administration.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.messenger.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("media/messages/<path:path>", _deny_private_media),
        path("media/avatars/<path:path>", _deny_private_media),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
