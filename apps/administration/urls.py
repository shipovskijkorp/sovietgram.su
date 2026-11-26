from django.urls import path
from . import views

app_name = "administration"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("operations/", views.operations_status, name="operations"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/action/", views.user_action, name="user_action"),
    path("communities/", views.communities, name="communities"),
    path("communities/<int:pk>/", views.community_detail, name="community_detail"),
    path("communities/<int:pk>/action/", views.community_action, name="community_action"),
    path("reports/", views.reports, name="reports"),
    path("reports/<int:pk>/", views.report_detail, name="report_detail"),
    path("reports/<int:pk>/action/", views.report_action, name="report_action"),
    path("audit/", views.audit, name="audit"),
    path("report/<str:kind>/<int:pk>/", views.submit_report, name="submit_report"),
    path("my-reports/", views.my_reports, name="my_reports"),
]
