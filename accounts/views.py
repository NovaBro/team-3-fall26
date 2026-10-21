from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render

from accounts.forms import SignupForm


def signup(request):
    if request.user.is_authenticated:
        return redirect("search:index")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Account created successfully. Welcome, {user.username}!")
            return redirect("search:index")
        if "email" in form.errors and any("already exists" in e for e in form.errors["email"]):
            messages.error(request, "An account with this email already exists.")
        else:
            messages.error(request, "Unable to register. Please fix the errors below.")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})
