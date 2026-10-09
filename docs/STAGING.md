# Staging nuevo: Railway + Neon

## Decisión y límites

Instalación **nueva**, sin importar registros, administradores ni media locales.
La base local PostgreSQL 14 y todos sus archivos se conservan sin cambios.
No exportar la liga local para este despliegue. No ejecutar ningún comando
remoto hasta obtener autorización independiente para cada operación.
Con autorización explícita, el 2026-10-09 se verificó Neon y se inicializó la
base nueva, con roles separados y todas las tablas inicialmente vacías.
Después, con autorización separada, se creó un administrador inicial.
No se importaron datos locales ni desplegó Railway. No repetir el bootstrap.
No existe todavía una URL HTTPS verificada desde Cuba.

| Campo | Destino aprobado |
| --- | --- |
| Proyecto Neon | `noisy-cloud-94939637` |
| Rama Neon | `production`, dedicada exclusivamente a staging |
| Base | `voli_staging_2026` |
| PostgreSQL | `18.6` |
| Repositorio / rama | `https://github.com/ndleon61/voleibol-con-jesus`, `main` |
| Media persistente | `/data/team-logos` |

La base remota `voleibolcuba` queda fuera del procedimiento. Si el destino
contiene objetos, detenerse: no borrar, limpiar ni sobrescribirlos. El guard
`restore-empty` conserva su restricción `voli_staging_`; no hay excepciones.

## Registro de inicialización autorizada: 2026-10-09

El proyecto/rama se confirmaron por el usuario en la consola Neon; SQL no
identifica esa correspondencia. El preflight y las conexiones siguientes
verificaron el host directo esperado, `voli_staging_2026`, PostgreSQL 18.6,
TLS con verify-full y channel_binding=require. La base estaba vacía antes
de cualquier escritura y antes de ejecutar el inicializador como mantenimiento.

Se aplicó staging-roles-before-schema.sql como neondb_owner: roles
voli_maintenance/voli_runtime sin superuser, CREATEDB, CREATEROLE, REPLICATION
ni BYPASSRLS, límites 3/5 conexiones, esquema public propiedad de mantenimiento,
CONNECT/TEMP revocados a PUBLIC y CREATE restringido. El primer intento de
asignar un verifier SCRAM generado por libpq fue rechazado por Neon después
del commit de roles. Se verificó el estado mediante consultas de solo lectura:
esquema todavía vacío, solo los dos roles nuevos esperados y sus flags/límites
correctos. No se recrearon, eliminaron ni cambiaron roles ajenos.

Para terminar, se asignaron únicamente las contraseñas de esos roles recién
creados mediante psycopg.ClientCursor y parámetros privados, plaintext sobre
TLS verificado con password_encryption=scram-sha-256. Neon no admite recibir
verifiers pre-hasheados. La plantilla ahora permite incluir los passwords
en CREATE ROLE; no contiene credenciales y no se ejecuta directamente en psql
sin un binding seguro. Nunca imprimir SQL renderizado ni usar literals de
contraseñas en comandos/chat. Neon/PostgreSQL almacena los hashes; esto no cambia
el hashing Werkzeug de futuros administradores de la aplicación.

Credenciales generadas aleatoriamente (48 bytes aleatorios por password) en
`.env.neon-staging`, Git-ignored y 600, con MAINTENANCE_DATABASE_URL y DATABASE_URL
(runtime). `.env.neon-preflight` permanece privado y 600. No poner mantenimiento
en Railway ni mostrar esos archivos. El valor SSL_CERT_FILE local apunta a
`/etc/ssl/cert.pem`: el OpenSSL del wheel buscaba un CA bundle inexistente en
`/tmp/libpq.build/`. Solo se ajustó el entorno del proceso; no se modificaron
certificados, dependencias Homebrew ni el PostgreSQL 14 local.

Tras un segundo preflight vacío como voli_maintenance, se invocó el comando
existente en un proceso CLI aislado, con directorio media temporal fuera del repo:

```text
init-staging --database-name voli_staging_2026 --empty-database-confirmed
```

Aplicó 000--006 en una transacción, retiró los placeholders originales dentro
de esa misma instalación nueva y validó los CHECK pendientes. No se ejecutó
create-admin. Se aplicó staging-runtime-after-schema.sql como mantenimiento.

Verificación final real, como voli_runtime, con transacciones read-only:

| Objetos | Resultado |
| --- | --- |
| Tablas | 10, todas vacías, propiedad de voli_maintenance |
| Secuencias | 6, generadores asociados y permisos USAGE/SELECT |
| Funciones | 11, propiedad de mantenimiento, EXECUTE disponible |
| Triggers | 9, todos habilitados |
| Índices | 21, todos válidos y listos |
| Vistas | 1: tournament_team_identities |
| Constraints | 72, todas validadas; incluye NOT NULL de PostgreSQL 18 |

Tablas: teams, seasons, tournaments, tournament_teams, jornadas, matches,
match_sets, administrators, administrator_sessions, administrator_login_attempts.
Todas tenían count=0, incluidos administradores, sesiones y resultados.

Runtime: CONNECT/USAGE; SELECT/INSERT/UPDATE/DELETE sobre tablas;
USAGE/SELECT sobre secuencias; EXECUTE sobre funciones y default privileges
para objetos futuros del propietario. Sin CREATE en base/esquema, TEMP,
TRUNCATE/TRIGGER, UPDATE de secuencias, ownership ni membresías (incluyendo
neon_superuser y voli_maintenance). Sus cinco flags administrativos son falsos.

Con Flask configurado explícitamente con runtime y conexiones read-only,
/api/seasons, /api/tournaments, /api/teams, /api/jornadas y /api/standings
respondieron 200 y []; /api/admin/teams devolvió 401 y /admin.html redirigió
303 a login. No se visitó login ni se crearon sesiones, uploads o registros.
La verificación fue con el test client de Flask, no un sitio desplegado.
Pasaron además 22 tests offline de preflight, seguridad del bootstrap y deployment;
no se ejecutó la suite de integración con fixtures contra Neon.

### Historial y huellas de migraciones

La arquitectura existente no tiene una tabla/ledger de migraciones. Este registro
documenta el bootstrap único 000--006 con sus SHA-256 y la inspección posterior
del catálogo; no se inventó un ledger ni se agregaron tablas de negocio nuevas.
No reejecutar init-staging: un destino ocupado se rechaza.

| Archivo | SHA-256 aplicado |
| --- | --- |
| 000_fresh_base.sql | a789f710f8803ef0bb1ea62c70c80bbd03354bc58cfbb3b8c42142d945dba199 |
| 001_admin_auth.sql | 75b7cc2385dea1c7b1ce3fb3e65f6c85f4a348b64345ec030791777307ca486b |
| 002_team_management.sql | 7856a69795a26f043a518e87029747c9ee991a8995481658b231702fbc34727d |
| 003_scheduling.sql | b0c26370da3f74b5ba214e3fa042aa31d1e80813db4524a31dcc927b60c7287c |
| 004_business_rules.sql | 45df047d54c018440e1bb4ee240588c153c7c4b66031cd891cdc0c7071937590 |
| 005_competitions.sql | 7321feb3208e4f34a4430781208c841e07b07427740b73123ba889e8f019b6be |
| 006_team_snapshots.sql | 749f69aa07de06e94e66d32cce1e6d6ec6b4911abafa337068c3a4d7a7a95717 |

El administrador inicial se creó posteriormente con autorización separada;
consultar el registro siguiente. No hay despliegue. Pendientes de verificación:
build/escaneo Docker, certificados dentro de la imagen,
Railway con volumen /data, secretos runtime, HTTPS, reinicio y pruebas desde Cuba.

### Administrador inicial autorizado: 2026-10-09

Se reconfirmaron destino, PostgreSQL 18.6, TLS verificado/channel binding y
ausencia de administradores. Se ejecutó el CLI existente create-admin para
`admin_staging` con password aleatorio fuerte, sin mostrarlo. La verificación
posterior read-only confirmó exactamente una cuenta activa, password hash
Werkzeug correcto y cero sesiones/intentos de login; no se realizó login.
Credenciales en `.env.neon-admin`, Git-ignored y permisos 600, nunca en esta guía.
El CLI solo añadió la cuenta; no creó equipos, torneos, resultados ni uploads.
La clave Flask del proceso CLI fue efímera y no es la futura clave de Railway.
Esta cuenta pertenece a Neon staging, no a la base usada por el localhost actual.
Local DB/media, roles, esquema y despliegue permanecieron sin cambios.

## Arquitectura y Railway

Un servicio desde la raíz del repositorio, Dockerfile, Python 3.12 y Gunicorn.
Frontend y API comparten origen, sin compilación Node, CDN ni fuentes externas.
No ejecutar migraciones al arrancar ni en pre-deploy. Un reinicio no crea datos.

| Ajuste | Valor |
| --- | --- |
| Root Directory / contexto | raíz (`/`), no `server-flask` |
| Builder | `Dockerfile` |
| Dependencias | `server-flask/requirements-production.txt`, dentro de la imagen |
| Start Command | sin override; conservar ENTRYPOINT y CMD |
| Comando efectivo | `gunicorn --chdir /app/server-flask --config /app/server-flask/gunicorn.conf.py app:app` |
| Puerto | `0.0.0.0:$PORT`, PORT suministrado por Railway |
| Réplicas | 1, dos workers sync, timeout 45 s |
| Volumen | `/data`, inicialmente 1 GB |
| Healthcheck | `/healthz`, timeout de despliegue 120 s |
| Reinicio | On Failure, 10 intentos; alertar al agotarse |
| Suspensión / serverless | desactivada inicialmente para medir latencia |
| Región | cercana a Neon y Cuba; confirmar latencia |
| Pre-deploy command | ninguno; el volumen no está disponible allí |

Desactivar autodeploys antes de conectar el repositorio: conectarlo puede iniciar
un despliegue. No crear servicios de pago ni conectar el origen sin aprobación.

Variables en el gestor de secretos, nunca en Git ni capturas:

| Variable | Valor |
| --- | --- |
| APP_ENV | `production` |
| STAGING | `1` |
| FLASK_DEBUG | `0` |
| FLASK_SECRET_KEY | clave aleatoria persistente, mínimo 32 caracteres, distinta de desarrollo |
| DATABASE_URL | conexión directa del rol `voli_runtime`, con base explícita |
| SSL_CERT_FILE | `/etc/ssl/certs/ca-certificates.crt` dentro del contenedor Linux; verificar existencia |
| TRUSTED_HOSTS | hostname HTTPS exacto y `healthcheck.railway.app`, separados por coma |
| TRUST_PROXY | `1` |
| PROXY_MODE | `railway` |
| TEAM_LOGO_DIRECTORY | `/data/team-logos` |
| RAILWAY_VOLUME_MOUNT_PATH | inyectada por Railway; comprobar `/data` |

DATABASE_URL debe incluir `sslmode=verify-full sslrootcert=system
channel_binding=require`; la aplicación rechaza el arranque si falta cualquiera.
La imagen configura SSL_CERT_FILE con el bundle CA de Linux indicado arriba;
no copiar el valor macOS de los archivos privados locales al contenedor.
Dos workers limitan la concurrencia normal a dos
solicitudes; conexiones cerradas por operación, connect_timeout 5 s, límites SQL
15 s y locks 5 s. No usar `-pooler`: snapshots y configuración transaccional
requieren sesión consistente. Mantenimiento también usa endpoint directo.

Railway termina TLS. El middleware usa X-Real-IP/X-Forwarded-Proto, no
X-Forwarded-For del cliente; comprobar que el edge sobrescribe esas cabeceras.
No exponer Gunicorn directamente. El probe HTTP interno solo admite GET/HEAD
de `/healthz` con host `healthcheck.railway.app`; las demás rutas exigen HTTPS.
Healthcheck consulta esquema y montaje escribible sin revelar diagnósticos.
Conservar CSP estricta, cookies Secure/HttpOnly/SameSite, CSRF y protección de
login. STAGING añade robots Disallow y X-Robots-Tag noindex: no impide lectura
pública ni sustituye autenticación. No cambiar la clave Flask al reiniciar.

## PostgreSQL 18 y herramientas

Los seis upgrades existentes presuponen tablas antiguas. La nueva base
`000_fresh_base.sql` se ejecuta **solo** mediante el comando protegido
`init-staging`, seguido de 001--006 dentro de una única transacción.
Se retiran únicamente los placeholders originales creados por 005 en esa
transacción vacía, sin registros importados. No se crean equipos, temporadas,
torneos ni cuentas de ejemplo. Se validan los CHECK históricos NOT VALID en el
esquema nuevo. Las instalaciones existentes siguen usando sus comandos actuales;
**no ejecutar 000 ni init-staging en la base local**.

El comando requiere confirmación, nombre explícito `voli_staging_...`, SSL
verify-full, conexión directa, versión 18.6+ de la rama 18 y ausencia de objetos
propios en toda la base. Usa el mismo bloqueo asesor que restore-empty y revierte
todo ante errores; no es idempotente sobre un esquema ocupado. Mantener el
destino sin otros escritores durante la inicialización.

Psycopg 3.3.6 binary local incorpora libpq 18.6 (180006). Verificar cada entorno:

```sh
.venv-clean/bin/python -c 'import psycopg; from psycopg import pq; print(psycopg.__version__, pq.version(), pq.__impl__)'
pg_dump --version
pg_restore --version
psql --version
```

El Dockerfile instala `postgresql-client-18` desde PGDG para Debian Trixie.
Antes de aprobar despliegue, construir, escanear y fijar digest base:

```sh
docker build --tag voli-staging:phase10 .
```

Docker/Podman no están disponibles localmente; la imagen no está verificada aún.
Homebrew falló al reenlazar ca-certificates 2026-09-25, ya enlazado. No ejecutar
brew unlink/link --overwrite ni cambiar PostgreSQL 14 para resolverlo.
La alternativa aislada compila el source oficial 18.6 con SHA-256 verificado,
prefix privado `/private/tmp/voli-pg18-build/install`, OpenSSL 3 existente sin
reenlazarlo, sin ICU/readline, y un cluster nuevo con TCP desactivado, socket
privado y puerto 55418. Este entorno no certifica TLS/collation de Neon ni Docker.
Clientes globales 14.19 permanecen intactos; añadir el bin 18 solo al proceso
de pruebas y backups 18, nunca globalmente a pruebas restore contra 14.

pg_dump 18 puede leer servidores 14 y 18; clientes 14/17 no pueden exportar 18.
Usar pg_dump/pg_restore/psql 18.6 o una revisión posterior de la rama 18 para
staging y recuperación. No asumir que un dump 18 puede volver a PostgreSQL 14.

## Procedimiento de instalación nueva (referencia; staging actual ya inicializado)

Los pasos de roles/esquema siguientes describen una instalación vacía futura.
No repetirlos en voli_staging_2026. Su ejecución autorizada figura arriba.

1. Completar pruebas aisladas 18 y construcción/escaneo de imagen.
2. Con aprobación, confirmar en consola proyecto, rama y destino. Si la base
   no existe, aprobar su creación vacía. Nunca usar una base compartida.
3. Aprobar preflight únicamente de lectura. Introducir en privado
   NEON_PREFLIGHT_DATABASE_URL, NEON_EXPECTED_HOST y NEON_EXPECTED_ROLE,
   endpoint directo confirmado, dbname explícito y SSL verificado:

   ```sh
   .venv-clean/bin/python server-flask/neon_preflight.py --read-only-approved
   ```

   Valida identidad, versión, TLS real, destino vacío y permisos de mantenimiento;
   solo SELECT, transacción read-only y rollback. No identifica proyecto/rama por
   SQL: la correspondencia endpoint/consola se verifica manualmente.
4. Con autorización separada, ejecutar
   [staging-roles-before-schema.sql](sql/staging-roles-before-schema.sql) como
   provisionador. Crea `voli_maintenance` y `voli_runtime` mediante SQL (no el
   gestor Neon que puede conceder neon_superuser), restringe CONNECT/CREATE/TEMP
   y asigna public a mantenimiento. Si los roles existen, falla sin cambiarlos.
   La plantilla requiere maintenance_password/runtime_password vinculados
   privadamente mediante psycopg.ClientCursor; generar y guardar los secretos
   antes de escribir. Incluye password_encryption=scram-sha-256. No suministrar
   verifiers pre-hasheados, que Neon rechaza. Si hay fallos parciales, inspeccionar
   estado read-only antes de continuar; nunca resetear roles ajenos.

5. Repetir preflight como mantenimiento antes de escribir. Con autorización
   independiente para crear el esquema, usar un servicio libpq privado
   `voli_neon_staging_owner` y PGPASSFILE 600. No poner credenciales en argv.
   Ejecutar desde raíz del repo en el entorno de mantenimiento:

   ```sh
   export DATABASE_URL='service=voli_neon_staging_owner dbname=voli_staging_2026 sslmode=verify-full'
   export STAGING=0 PROXY_MODE=standard TRUST_PROXY=0
   export TEAM_LOGO_DIRECTORY='/ruta/privada/staging-media-vacia'
   .venv-clean/bin/python -m flask --app server-flask/app.py init-staging \
     --database-name voli_staging_2026 --empty-database-confirmed
   .venv-clean/bin/python -m flask --app server-flask/app.py create-admin
   ```

   Estas variables solo afectan el CLI, no Railway. Usar una clave Flask privada
   mediante entorno/gestor seguro y APP_ENV adecuado; el CLI no abre servidor HTTP.
   create-admin pide usuario y contraseña sin eco con confirmación, 12--128
   caracteres y hash Werkzeug. No usar cuentas ni contraseñas de desarrollo.
   No crear una cuenta durante esta preparación. Si falla init-staging, revisar
   privadamente; no borrar objetos inesperados ni repetir a ciegas.
6. Como `voli_maintenance`, ejecutar
   [staging-runtime-after-schema.sql](sql/staging-runtime-after-schema.sql).
   Otorga DML/tablas, secuencias y funciones y permisos futuros del propietario.
   Runtime no recibe ownership, CREATE DATABASE/ROLE, bypass RLS ni membresía
   de mantenimiento/neon_superuser. Verificar flags y membresías falsas.
7. Aprobar por separado Railway, volumen, secretos, dominio y primer despliegue.
   DATABASE_URL del web pertenece solo a runtime; mantenimiento nunca queda
   permanentemente en sus variables. Comprobar cuotas, suspensión y facturación.

## Volumen nuevo y workflow de aceptación

Montar `/data` y crear `/data/team-logos` vacío mediante el entrypoint, propietario
UID/GID 10001. No transferir archivos locales ni bundles antiguos. Los originales
públicos `/media/` son assets del repositorio incluidos en la imagen, no uploads.
Los logos nuevos y snapshots se conservan en el volumen; no borrarlos al editar
equipos. No dar permisos globales ni aplicar chown recursivo a datos ajenos.

El esquema vacío devuelve catálogos públicos vacíos, no una liga de ejemplo.
Después de login en `/login`, probar en móvil y desktop:

- Crear una temporada activa y un torneo activo; marcar el torneo público.
- Crear dos equipos, subir un logo y registrar ambos en ese torneo.
- Crear jornada, programar partido con fecha/hora America/Havana.
- Rechazar equipo contra sí mismo, duplicado y horario solapado.
- Registrar tres sets válidos (p. ej. 25--10); comprobar calendario/resultados.
- Comprobar standings: ganador 1 victoria/3 sets, rival 1 derrota/3 sets perdidos.
- Corregir el resultado dentro del torneo abierto, sin duplicados.
- Cerrar torneo; comprobar captura de nombre/logo. Renombrar o quitar logo global
  y verificar identidad histórica intacta; archivar y rechazar modificaciones.
- Logout, sesión expirada, acceso sin autenticar y CSRF inválido rechazados.
- Reiniciar Railway; verificar datos, logo actual e histórico sin pérdida.

La prueba automatizada test_initialization.py cubre el recorrido API autenticado
desde base nueva, rollback y rechazo del destino ocupado. Las suites browser
validan el dashboard con fixtures; no equivalen a probarlo desplegado en Neon.

Con HTTPS_URL configurado, antes y después de reinicio autorizado:

```sh
.venv-clean/bin/python scripts/verify_staging.py --url "$HTTPS_URL" \
  --login --record /ruta/privada/staging-before.json
# Reiniciar solo el servicio staging desde Railway, sin editar datos.
.venv-clean/bin/python scripts/verify_staging.py --url "$HTTPS_URL" \
  --login --compare /ruta/privada/staging-before.json
```

Prompts sin eco; sin cookies persistidas. Revisa APIs, login/logout, cookies,
401, redirección, CSP, robots, healthcheck y bytes de media públicos. Verificar
manualmente HTTPS, trusted hosts, proxy y assets históricos de otros torneos.

## Backups y recuperación del staging futuro

Con datos nuevos: backup diario y antes de upgrades, ventana sin escritores,
copiar **Neon staging y su volumen**, nunca la liga local para poblar staging.
Desde mantenimiento con acceso a media y clientes 18, secretos privados:

```sh
umask 077
export DATABASE_URL='service=voli_neon_staging_owner dbname=voli_staging_2026 sslmode=verify-full'
python /app/server-flask/backup.py backup --logos /data/team-logos \
  --output /ruta/privada/backup/FECHA --maintenance-confirmed
```

Bundle nuevo, archivos 600/directorios 700, checksums y tar sin enlaces/traversal.
Contiene hashes de administradores: cifrar en reposo/tránsito, fuera del repo y
fuera de Railway. Retención propuesta 7 diarias/4 semanales, ensayo mensual.
No guardar credenciales de mantenimiento permanentemente en el servicio web.

Para ensayo local, restore crea solo una base nueva `voli_restore_...`.
En Neon, autorizar otra base vacía `voli_staging_...` y volumen nuevo, preflight
y roles independientes. Nunca restaurar encima del staging activo:

```sh
python server-flask/backup.py restore-empty --source "$BUNDLE" \
  --database-name "$RECOVERY_DATABASE_NAME" --empty-target-confirmed
python server-flask/backup.py restore-media --source "$BUNDLE" --logos "$RECOVERY_LOGOS"
python server-flask/backup.py verify-media --source "$BUNDLE" --logos "$RECOVERY_LOGOS"
python server-flask/backup.py verify-transfer
```

DATABASE_URL debe apuntar explícitamente a recuperación, SOURCE_DATABASE_URL al
staging detenido para verify-transfer. restore usa transacción única, sin clean,
DROP ni overwrite; conserva admins/historia y descarta sesiones/intentos de login.
No ejecutar init-staging sobre un dump restaurado: ya contiene el esquema.
Tras restaurar, conceder runtime como propietario real, verificar media 600/700,
datos/secuencias/triggers y smoke tests antes de cambiar referencias.

Rollback de código: despliegue anterior compatible con escrituras detenidas,
conservando secretos y volumen; no ejecutar migraciones inversas. Recuperación
de datos: otra base/volumen, verificar y cambiar referencias bajo mantenimiento,
conservar destinos anteriores. Neon PITR no sustituye DB+media coordinados.

## Pruebas, recursos y pendientes

La revisión final pasó **135 tests Python**, sin skips, contra el servidor
aislado PostgreSQL **18.6**, con pg_dump/pg_restore/psql **18.6**. Incluye las
migraciones existentes, bootstrap vacío, validación de constraints, recorrido
autenticado completo, rollback ante fallo, concurrencia, aislamiento de torneos,
snapshots y backup/restauración en bases nuevas. Tres tests de instalación nueva
también pasaron por separado. No se usaron registros ni uploads de la liga local.
La suite emitió un ResourceWarning no fatal de archivo sin cerrar.

Pasaron **31 tests JavaScript** y suites browser públicas/admin Chromium y
WebKit, incluyendo 320--430 px. Slow 3G: datos listos en 2638--2642 ms, FCP
1580--1588 ms, recursos completos 3826--3852 ms, 82 971 bytes y CLS 0.000731.
Las suites browser usaron el servidor local/fixtures, no un despliegue remoto.
No hubo errores JavaScript/CSP de la aplicación ni desbordamiento horizontal.
WebKit registró las advertencias conocidas del selector nativo y del harness
de screenshots, sin fallos de las suites. La revisión de archivos candidatos
no encontró secretos ni backups; los tres archivos privados Neon permanecen
ignorados, sin seguimiento Git y con permisos 600.

**Gate PostgreSQL 18: aprobado localmente** para esquema, operaciones y recovery.
El cluster usó socket Unix privado (sslmode no negocia TLS en sockets), locale C,
sin ICU; TLS/collation Neon y permisos de sus roles no se certificaron.
Los clientes globales siguen en PostgreSQL 14.19. No se cambiaron enlaces
Homebrew, configuración, registros ni media del PostgreSQL 14 existente.
Se detuvo únicamente el cluster temporal 18 después de las pruebas.

Para repetir, arrancar exclusivamente ese cluster privado (si todavía existe)
y limitar el PATH al proceso de prueba:

```sh
/private/tmp/voli-pg18-build/install/bin/pg_ctl \
  -D /private/tmp/voli-pg18-build/cluster \
  -l /private/tmp/voli-pg18-build/server.log \
  -o "-k /private/tmp/voli-pg18-build/socket -p 55418 -c listen_addresses='' -c max_connections=30 -c shared_buffers=32MB" start
AUTH_TEST_DATABASE_URL='host=/private/tmp/voli-pg18-build/socket port=55418 dbname=voli_staging_integration' \
PATH="/private/tmp/voli-pg18-build/install/bin:$PATH" \
.venv-clean/bin/python -m unittest discover -s server-flask -p 'test_*.py'
node --test tests/*.test.cjs
/private/tmp/voli-pg18-build/install/bin/pg_ctl \
  -D /private/tmp/voli-pg18-build/cluster stop -m fast
```

TLS Neon y roles/esquema/runtime ya fueron verificados con autorización; consultar
el registro arriba. Montaje/reinicio Railway y construcción Docker siguen pendientes.
La cuenta inicial se autorizó y creó por separado. La revisión final de solo
lectura confirmó PostgreSQL 18.6, el rol runtime y exactamente un administrador
staging activo con TLS verificado y channel binding obligatorio, sin escrituras.
Commit y push del código Phase 10 se autorizaron para esta revisión;
el despliegue Railway sigue sin autorización y no se realizó.

Estimación inicial: 1 réplica, 512 MB RAM (1 GB si Pillow/carga lo requieren),
2 workers, volumen 1 GB, Neon 0.25 CU. Revisar cuotas/precios actuales antes de
aprobar servicios; medir latencia fría y consumo, no prometer coste fijo.

- Probar sin VPN con dos operadores cubanos, Wi-Fi y datos, Safari/Chrome.
- Anchos 320/360/390/430 px, teclado abierto y orientación.
- Medir visita fría/caliente y después de suspensión Neon; DNS/TLS/bytes/datos.
- Recorrer calendario/resultados/tabla, filtros y workflow administrativo completo.
- Cortar red durante envío; mensajes en español y sin duplicar resultados.
- Slow 3G local: 400 ms, 400 kbit/s, CPU x4; datos <=5 s, FCP <=3 s,
  recursos <=10 s, CLS <0.1. No ampliar presupuestos para ocultar fallos.
- Reiniciar servicio y verificar historia/media; no compartir HAR con secretos.

Referencias oficiales:
[PostgreSQL 18.6 source](https://www.postgresql.org/ftp/source/v18.6/),
[requisitos de compilación](https://www.postgresql.org/docs/18/install-requirements.html),
[pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html),
[PGDG Debian](https://www.postgresql.org/download/linux/debian/),
[Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html),
[Railway build](https://docs.railway.com/builds/build-and-start-commands),
[volúmenes](https://docs.railway.com/volumes/reference),
[healthcheck](https://docs.railway.com/deployments/healthchecks),
[proxy](https://docs.railway.com/networking/public-networking/specs-and-limits),
[roles Neon](https://github.com/neondatabase/website/blob/main/content/docs/manage/roles.md).
