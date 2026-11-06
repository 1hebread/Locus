# Third-Party Notices

Locus is distributed under the [MIT License](LICENSE). It bundles and depends on the third-party components listed below. Exact resolved versions are recorded in [`uv.lock`](uv.lock); license texts ship with each package in `site-packages/*.dist-info/`.

This list is provided for convenience and may be incomplete or outdated. It is not legal advice — when in doubt, check the license shipped with the package itself.

## Bundled in the repository

| Component | Version | License | Location |
|---|---|---|---|
| [HTMX](https://htmx.org) | 2.0.4 | 0BSD | `src/locus/static/js/htmx.min.js` |
| [Tailwind CSS](https://tailwindcss.com) | build-time only | MIT | `src/locus/static/css/tailwind.css` (compiled output) |

## Python runtime dependencies

| Package | License | Used for |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | Web framework |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause | ASGI toolkit |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | ASGI server |
| [uvloop](https://github.com/MagicStack/uvloop) | MIT | Event loop |
| [httptools](https://github.com/MagicStack/httptools) | MIT | HTTP parsing |
| [watchfiles](https://github.com/samuelcolvin/watchfiles) | MIT | Reload watcher |
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause | WebSocket support |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | MIT | ORM |
| [asyncpg](https://github.com/MagicStack/asyncpg) | Apache-2.0 | PostgreSQL driver |
| [Alembic](https://github.com/sqlalchemy/alembic) | MIT | Migrations |
| [Mako](https://github.com/sqlalchemy/mako) | MIT | Alembic templates |
| [Pydantic](https://github.com/pydantic/pydantic), [pydantic-settings](https://github.com/pydantic/pydantic-settings) | MIT | Validation and settings |
| [annotated-types](https://github.com/annotated-types/annotated-types) | MIT | Typing helpers |
| [typing-extensions](https://github.com/python/typing_extensions) | PSF-2.0 | Backports |
| [PyJWT](https://github.com/jpadilla/pyjwt) | MIT | JWT tokens |
| [bcrypt](https://github.com/pyca/bcrypt) | Apache-2.0 | Password hashing |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 OR BSD-3-Clause | Fernet encryption |
| [greenlet](https://github.com/python-greenlet/greenlet) | MIT AND PSF-2.0 | Async SQLAlchemy |
| [Jinja2](https://github.com/pallets/jinja) | BSD-3-Clause | Templates |
| [MarkupSafe](https://github.com/pallets/markupsafe) | BSD-3-Clause | Template escaping |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | Form parsing |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | `.env` loading |
| [pywebpush](https://github.com/web-push-libs/pywebpush) | MPL-2.0 | Web Push delivery |
| [py-vapid](https://github.com/web-push-libs/vapid) | MPL-2.0 | VAPID signing |
| [http-ece](https://github.com/web-push-libs/encrypted-content-encoding) | MIT | Payload encryption |
| [requests](https://github.com/psf/requests) | Apache-2.0 | HTTP client for push |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 | CA bundle |

## Mozilla Public License 2.0

`pywebpush`, `py-vapid` and `certifi` are licensed under the MPL-2.0. They are used here **unmodified**, as published on PyPI, and are not bundled into this repository's source tree. Their source is available at the links above and from <https://pypi.org>.

If you modify any MPL-2.0–covered file, you must make the modified source available under the MPL-2.0. The full license text is available at <https://mozilla.org/MPL/2.0/>.

## Frontend tooling (development only)

| Package | License | Used for |
|---|---|---|
| [Tailwind CSS](https://tailwindcss.com) | MIT | Compiling `static/css/tailwind.css` |

Node.js tooling is not required to run Locus: the compiled CSS is committed to the repository.
