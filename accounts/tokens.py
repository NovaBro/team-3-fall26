from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Own key salt so a verification link can't double as a password-reset token."""

    key_salt = "accounts.EmailVerificationTokenGenerator"


email_verification_token = EmailVerificationTokenGenerator()
