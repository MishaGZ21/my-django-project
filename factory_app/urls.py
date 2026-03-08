from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(template_name="login.html"), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('', include('core.urls')),
    path('contracts/', include('contracts.urls', namespace='contracts')),
]


# Custom 403 handler
from django.shortcuts import render

def handler403(request, exception=None):
    return render(request, '403.html', status=403)
