"""Base settings shipped with the spoor package.

A deployment imports these and adds everything environment-specific (secrets,
database, hosts, broker). This repo's own deployment is `config/settings.py`;
a downstream project extends this module the same way instead of copying it.
"""

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "spoor",
    "spoor.modules.chains",
    "spoor.modules.labels",
    "spoor.modules.cases",
    "spoor.modules.screening",
    "spoor.modules.tracing",
    "spoor.modules.reports",
    "spoor.modules.contracts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Heuristics evaluated on every finished trace (see spoor.modules.tracing.heuristics).
SPOOR_HEURISTICS = [
    "spoor.modules.tracing.heuristics.CollectionWallet",
]

# Static checks run on every analyzed contract (see spoor.modules.contracts.checks).
SPOOR_CONTRACT_CHECKS = [
    "spoor.modules.contracts.checks.PrivilegedMint",
    "spoor.modules.contracts.checks.TransferBlocklist",
    "spoor.modules.contracts.checks.ModifiableFees",
    "spoor.modules.contracts.checks.TradingControls",
    "spoor.modules.contracts.checks.Upgradeable",
    "spoor.modules.contracts.checks.HiddenOwnership",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "spoor.common.exceptions.exception_handler",
}
