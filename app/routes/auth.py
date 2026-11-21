"""Auth routes: sign up, email verification, login, logout, password reset.

Routes stay thin: validate the form, call `app.services.auth_service`, flash, redirect.
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from app import auth_utils
from app.auth_utils import logged_out_only, safe_next
from app.forms import ForgotPasswordForm, LoginForm, ResendForm, ResetPasswordForm, SignupForm
from app.services import auth_service
from app.services.auth_service import AuthError

auth_bp = Blueprint("auth", __name__)

RESEND_MESSAGE = "If that account needs verifying, we've sent a new link."
RESET_MESSAGE = "If an account exists for that email, we've sent a reset link."

# Reset-password errors where the user can simply retry on the same page.
_RETRYABLE_CODES = {"weak_password", "same_password", "rate_limit", "email_limit", "unknown", "unavailable"}


# Real Supabase JWTs are well under 2 KB; anything bigger is not one.
_MAX_TOKEN_LENGTH = 4096


def _link_error(kind: str):
    return render_template("auth/link_error.html", kind=kind), 400


# --- Sign up and email verification -----------------------------------------


@auth_bp.route("/signup", methods=["GET", "POST"])
@logged_out_only
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        try:
            auth_service.sign_up(form.email.data, form.password.data, form.name.data)
        except AuthError as error:
            if error.field and hasattr(form, error.field):
                getattr(form, error.field).errors.append(error.user_message)
            else:
                flash(error.user_message, "error")
        else:
            session["pending_email"] = form.email.data
            return redirect(url_for("auth.check_email"))
    return render_template("auth/signup.html", form=form)


@auth_bp.route("/check-email")
def check_email():
    return render_template(
        "auth/check_email.html",
        email=session.get("pending_email"),
        form=ResendForm(),
    )


@auth_bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    form = ResendForm()
    if not form.validate_on_submit():
        return render_template("auth/check_email.html", email=session.get("pending_email"), form=form)

    email = session.get("pending_email") or form.email.data
    if not email:
        flash("Please enter your email address.", "error")
        return redirect(url_for("auth.check_email"))

    try:
        auth_service.resend_verification(email)
    except AuthError as error:
        flash(error.user_message, "error")
    else:
        flash(RESEND_MESSAGE, "success")
    return redirect(url_for("auth.check_email"))


def _complete_link(kind: str, data: auth_service.SessionData) -> str:
    """Finish a verified email link and return the URL to send the user to."""
    if kind == "signup":
        auth_utils.save_login(data)
        flash("Email verified. Welcome to Pocketly!", "success")
        return url_for("expenses.dashboard")

    # Recovery: keep the tokens apart from `auth`, so the user isn't logged in
    # until they have set a new password.
    session.pop("auth", None)
    session["recovery"] = {"access_token": data.access_token, "refresh_token": data.refresh_token}
    return url_for("auth.reset_password")


@auth_bp.route("/auth/confirm")
def confirm():
    token_hash = request.args.get("token_hash", "").strip()

    if not token_hash:
        # Supabase's default flow puts the tokens in the URL fragment (#...), which
        # the server never sees. A small script reads it and posts to /auth/session.
        return render_template("auth/verifying.html")

    link_type = request.args.get("type", "").strip()
    if link_type in ("email", "signup"):
        kind, otp_type = "signup", "email"
    elif link_type == "recovery":
        kind, otp_type = "recovery", "recovery"
    else:
        return _link_error("signup")

    try:
        data = auth_service.verify_link(token_hash, otp_type)
    except AuthError as error:
        if error.code == "link_invalid":
            return _link_error(kind)
        flash(error.user_message, "error")
        return redirect(url_for("auth.login"))

    return redirect(_complete_link(kind, data))


@auth_bp.route("/auth/session", methods=["POST"])
def establish_session():
    """Receive the tokens from the URL fragment, check them with Supabase, then log in.

    Called by the script on the "Verifying..." page. Replies with JSON holding the
    URL to go to next. CSRF is checked by Flask-WTF through the X-CSRFToken header.
    """
    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    link_type = payload.get("type")

    if link_type in ("signup", "email"):
        kind = "signup"
    elif link_type == "recovery":
        kind = "recovery"
    else:
        kind = None

    tokens_ok = all(isinstance(t, str) and 0 < len(t) <= _MAX_TOKEN_LENGTH for t in (access_token, refresh_token))
    if kind is None or not tokens_ok:
        return jsonify(redirect=url_for("auth.link_error")), 400

    try:
        data = auth_service.verify_tokens(access_token, refresh_token)
    except AuthError as error:
        if error.code == "link_invalid":
            return jsonify(redirect=url_for("auth.link_error", kind=kind)), 400
        flash(error.user_message, "error")
        return jsonify(redirect=url_for("auth.login")), 503

    return jsonify(redirect=_complete_link(kind, data))


@auth_bp.route("/auth/link-error")
def link_error():
    kind = request.args.get("kind")
    return _link_error(kind if kind in ("signup", "recovery") else "unknown")


# --- Log in and out ---------------------------------------------------------


@auth_bp.route("/login", methods=["GET", "POST"])
@logged_out_only
def login():
    next_url = safe_next(request.args.get("next"))
    form = LoginForm()
    show_resend = False

    if form.validate_on_submit():
        try:
            data = auth_service.sign_in(form.email.data, form.password.data)
        except AuthError as error:
            flash(error.user_message, "error")
            if error.code == "email_not_confirmed":
                session["pending_email"] = form.email.data
                show_resend = True
        else:
            auth_utils.save_login(data)
            return redirect(next_url or url_for("expenses.dashboard"))

    return render_template("auth/login.html", form=form, next_url=next_url, show_resend=show_resend)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    token = auth_utils.access_token()
    if token:
        try:
            auth_service.sign_out(token)
        except AuthError:
            pass  # We clear the local session either way.
        auth_utils.clear_login()
        flash("You've been logged out.", "success")
    return redirect(url_for("main.landing"))


# --- Forgot / reset password ------------------------------------------------


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@logged_out_only
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        try:
            auth_service.send_reset(form.email.data)
        except AuthError as error:
            flash(error.user_message, "error")
        else:
            flash(RESET_MESSAGE, "success")
        return redirect(url_for("auth.forgot_password"))
    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    recovery = session.get("recovery")
    if not recovery:
        flash("Please request a new reset link.", "error")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            data = auth_service.update_password(
                recovery["access_token"], recovery["refresh_token"], form.password.data
            )
        except AuthError as error:
            if error.field and hasattr(form, error.field):
                getattr(form, error.field).errors.append(error.user_message)
            elif error.code in _RETRYABLE_CODES:
                flash(error.user_message, "error")
            else:
                # The recovery tokens are no longer usable.
                session.pop("recovery", None)
                flash("Your reset link has expired. Please request a new one.", "error")
                return redirect(url_for("auth.forgot_password"))
        else:
            auth_utils.save_login(data)  # also drops the recovery tokens
            flash("Password updated.", "success")
            return redirect(url_for("expenses.dashboard"))
    return render_template("auth/reset_password.html", form=form)
