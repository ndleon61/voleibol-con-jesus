# Voli Conociendo a Jesús

## Desarrollo local

Ejecuta estos comandos desde la raíz del proyecto, con PostgreSQL disponible
y la base de datos `voleibolcuba` existente:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r server-flask/requirements.txt
export DATABASE_URL='dbname=voleibolcuba'
export APP_ENV=development
export FLASK_SECRET_KEY="$(openssl rand -hex 32)"
.venv/bin/python -m flask --app server-flask/app.py init-auth
.venv/bin/python -m flask --app server-flask/app.py init-teams
.venv/bin/python -m flask --app server-flask/app.py init-scheduling
.venv/bin/python -m flask --app server-flask/app.py init-business-rules
.venv/bin/python -m flask --app server-flask/app.py init-competitions
.venv/bin/python -m flask --app server-flask/app.py init-snapshots
.venv/bin/python -m flask --app server-flask/app.py create-admin --username administrador
.venv/bin/python server-flask/app.py
```

Abre `http://127.0.0.1:3000/` para la liga o
`http://127.0.0.1:3000/login` para la administración.
Flask sirve las páginas y la API desde el mismo origen. Para publicar con
otro servidor, las rutas `/api/` deben dirigirse al backend.

`PORT` cambia el puerto, `HOST` cambia la interfaz de escucha y
`FLASK_DEBUG=1` activa la depuración solo en desarrollo. Si el puerto está
ocupado, usa `PORT=3001 .venv/bin/python server-flask/app.py`.

La contraseña se solicita dos veces sin mostrarla en la terminal. Usa una
contraseña única de entre 12 y 128 caracteres, preferiblemente generada por
un gestor de contraseñas. No se acepta la contraseña como argumento ni se
guarda en texto plano; Werkzeug genera un hash scrypt con sal aleatoria.
El usuario admite entre 3 y 64 letras ASCII, números, puntos, guiones y
guiones bajos, y se normaliza a minúsculas.

La clave generada dura en esta sesión de terminal. Para conservar sesiones
entre reinicios, proporciona la misma `FLASK_SECRET_KEY` mediante variables
de entorno administradas por tu servidor o un gestor de secretos. No
incluyas claves reales ni contraseñas de PostgreSQL en Git. Cambiar la clave
invalida las cookies existentes. El servidor no arranca sin una clave de
al menos 32 caracteres.

## Base de datos

`init-auth` aplica `server-flask/migrations/001_admin_auth.sql` dentro de una
transacción. Es idempotente y solo añade:

- `administrators`: usuario, hash de contraseña, estado activo y fecha.
- `administrator_sessions`: hash SHA-256 del identificador, datos de sesión
  y vencimiento. La cookie contiene solo un identificador aleatorio firmado.
- `administrator_login_attempts`: contadores identificados mediante HMAC,
  sin guardar las direcciones IP en texto plano.

No se recrean ni se eliminan equipos, jornadas, partidos o resultados.
Todas las consultas con valores utilizan parámetros. No se exponen hashes
de contraseñas ni configuración sensible a través de la API.

## Gestión de equipos

Antes de iniciar una instalación existente, instala las dependencias y ejecuta:

```sh
.venv/bin/python -m pip install -r server-flask/requirements.txt
.venv/bin/python -m flask --app server-flask/app.py init-teams
```

`init-teams` aplica `server-flask/migrations/002_team_management.sql`: añade
`logo_path` si falta, un generador de identificadores cuando es necesario y
un índice único de nombres sin distinguir mayúsculas. No elimina datos ni
cambia identificadores. Si encuentra nombres duplicados, cancela la
transacción para que puedan corregirse sin perder el historial. La primera
ejecución vincula los logotipos originales disponibles; las posteriores no
restauran logotipos eliminados por un administrador.

En el panel, «Equipos» permite registrar, editar y eliminar equipos. Los
equipos con partidos asociados no se pueden eliminar. Cambiar el nombre
conserva sus partidos y resultados. Las modificaciones requieren sesión y
CSRF; `GET /api/teams` sigue siendo público. La administración utiliza
`GET/POST /api/admin/teams` y `PUT/DELETE /api/admin/teams/<id>`.

Se aceptan JPEG, PNG y WebP de hasta 2 MB y 16 millones de píxeles. Pillow
verifica y convierte las imágenes a WebP, limita sus dimensiones a 1024 px
y descarta nombres originales y metadatos. Los archivos se guardan fuera
del directorio público, en `server-flask/instance/team-logos`, con nombres
aleatorios. `TEAM_LOGO_DIRECTORY` permite elegir un directorio persistente.
El usuario del servidor necesita permiso de escritura; incluye este
directorio y PostgreSQL en tus copias de seguridad. Los logotipos son
públicos y se sirven mediante `/team-logos/`; no subas imágenes privadas.

## Jornadas y programación

Para actualizar una instalación existente, configura las mismas variables de
entorno que utiliza el servidor y ejecuta antes de reiniciarlo:

```sh
.venv/bin/python -m flask --app server-flask/app.py init-scheduling
```

`server-flask/migrations/003_scheduling.sql` añade `matches.scheduled_at`
(`TIMESTAMPTZ`), generadores de identificadores cuando faltan y protección
contra números de jornada y partidos duplicados. Es idempotente y no
reescribe ni elimina los equipos, jornadas, partidos o resultados existentes.
Las fechas históricas desconocidas permanecen `NULL`; su hora original se
conserva y aparece como «Fecha por confirmar» en la administración.

La fecha y hora introducidas se interpretan en `America/Havana`, incluido
su horario de verano. Se convierten a UTC y PostgreSQL guarda un instante
absoluto en `TIMESTAMPTZ`. La API entrega `startsAt` con desplazamiento UTC,
`date` en Cuba y conserva `time` en formato de 24 horas. El navegador muestra
las fechas en español y en la zona de Cuba, independientemente de su zona
local. Se rechazan horas inexistentes o ambiguas durante cambios de horario.
Mantén actualizada la base de zonas horarias IANA del sistema operativo.
`match_time` se conserva para los registros históricos y se sincroniza con
la hora local al programar o reprogramar un partido.

«Gestión de jornadas» permite crear y editar jornadas, seleccionar una para
programar partidos y confirmar eliminaciones. Solo se eliminan jornadas
vacías y partidos sin resultados. Un partido finalizado o con cualquier set
registrado no admite cambios de equipos ni eliminación; sí permite corregir
su fecha y hora sin modificar resultados. Los partidos nuevos aparecen al
cargar el calendario público, y los finalizados permanecen en resultados.

Rutas protegidas por sesión y CSRF para modificaciones:

- `GET/POST /api/admin/jornadas`
- `PUT/DELETE /api/admin/jornadas/<id>`
- `POST /api/admin/jornadas/<id>/matches`
- `PUT/DELETE /api/admin/matches/<id>`

`GET /api/jornadas` sigue siendo público, con los mismos campos anteriores
y los campos opcionales `startsAt` y `date`. La detección de duplicados usa
jornada, pareja de equipos (sin importar su orden) y fecha/hora. En partidos
históricos sin fecha se compara su hora original, para evitar copiarlos por
error. Los bloqueos y restricciones de PostgreSQL protegen el historial
frente a escrituras concurrentes.

## Validación e integridad

Para actualizar una instalación existente, con sus variables de entorno:

```sh
.venv/bin/python -m flask --app server-flask/app.py init-business-rules
```

`004_business_rules.sql` añade `matches.duration_minutes`, con 120 minutos
por defecto. La API admite `durationMinutes` opcional, entero de 1 a 1440;
al editar un partido sin este campo se conserva su duración anterior.
Los intervalos son `[inicio, fin)`: un equipo puede jugar justo al terminar
su turno anterior, pero nunca durante él. Los conflictos se comprueban
también entre jornadas diferentes, con fecha y hora absolutas, incluidos
partidos que cruzan la medianoche. La misma pareja y fecha/hora se rechaza
como duplicado aunque se intente registrar en otra jornada.

Los partidos históricos sin fecha se conservan. Para compararlos con un
partido fechado de la misma jornada, se interpreta su hora en la fecha
local propuesta. Sin una fecha histórica real no es posible detectar todos
los conflictos entre jornadas o días diferentes: completa las fechas desde
la administración cuando se conozcan. No se bloquean fechas pasadas, porque
son necesarias para registrar y corregir resultados históricos.

Los bloqueos de equipos en orden de identificador serializan las escrituras
que comparten participantes. Los disparadores PostgreSQL rechazan horarios
solapados, duplicados y la eliminación o cambio de participantes/jornada de
partidos con resultados. No se necesitan extensiones de PostgreSQL. Las
escrituras de la aplicación utilizan el aislamiento estándar READ COMMITTED;
las lecturas públicas de jornadas y clasificación usan una instantánea
REPEATABLE READ para no mezclar datos durante una corrección concurrente.

Las nuevas comprobaciones de duración, hora local, numeración de sets y
puntos se crean con `NOT VALID`: conservan registros históricos y se aplican
a nuevas escrituras. La validación completa de un resultado sigue siendo
responsabilidad de `validate_sets`, compartida por resultados y clasificación.
Los accesos SQL directos requieren un usuario de base de datos de confianza;
las comprobaciones básicas no sustituyen la validación de un partido completo.

Un resultado válido termina con tres sets ganados, entre tres y cinco sets.
Los sets 1–4 terminan en 25 puntos, o con ventaja exacta de dos si hay
prórroga; el quinto termina en 15 con la misma regla. No se aceptan sets
posteriores a la tercera victoria, empates, fracciones, valores negativos,
booleanos ni puntos superiores a 2147483647 (límite de PostgreSQL INTEGER).
Si se proporciona `setNumber`, debe ser consecutivo desde 1.

La clasificación solo cuenta partidos finalizados y válidos. Desempata por
victorias, diferencia de sets, sets ganados y nombre en minúsculas, en orden
Unicode consistente entre Python y JavaScript. Las correcciones reemplazan
los sets en una transacción, sin duplicarlos; un fallo conserva el resultado
anterior. Dos correcciones concurrentes se serializan y prevalece la última
transacción confirmada. Los conflictos de concurrencia devuelven 409 con un
mensaje en español para recargar y reintentar.

## Temporadas y torneos

Con PostgreSQL disponible y las variables de entorno del servidor, realiza una
copia de seguridad y aplica las migraciones antes de reiniciar Flask:

```sh
pg_dump "$DATABASE_URL" --format=custom --file=/tmp/voli-antes-de-temporadas.dump
.venv/bin/python -m flask --app server-flask/app.py init-auth
.venv/bin/python -m flask --app server-flask/app.py init-teams
.venv/bin/python -m flask --app server-flask/app.py init-scheduling
.venv/bin/python -m flask --app server-flask/app.py init-business-rules
.venv/bin/python -m flask --app server-flask/app.py init-competitions
.venv/bin/python -m flask --app server-flask/app.py init-snapshots
PORT=3001 .venv/bin/python server-flask/app.py
```

`005_competitions.sql` añade `seasons`, `tournaments`, `tournament_teams` y
`jornadas.tournament_id`. Los partidos y sets conservan sus relaciones e
identificadores. La primera ejecución crea «Temporada original» y «Torneo
original», inscribe los equipos existentes y vincula sus jornadas. No cambia
logotipos, horarios, puntuaciones ni cuentas administrativas. Las fechas
desconocidas permanecen vacías. También repara generadores de identificadores
ausentes utilizando el esquema real de las tablas existentes.

El número de jornada es único dentro de cada torneo. Los conflictos de horarios
y duplicados se comprueban dentro del torneo; un mismo equipo puede estar
inscrito en varios torneos. No se comprueban solapamientos entre torneos
diferentes. Las claves externas impiden eliminar datos históricos por cascada.
La migración puede repetirse sin duplicar registros, restaurar inscripciones
retiradas ni cambiar el torneo público seleccionado. Una vez instalada, los
comandos antiguos `init-scheduling` e `init-business-rules` mantienen estas
reglas en lugar de reinstalar restricciones globales antiguas.

No hay variables de entorno ni dependencias nuevas. Los equipos y sus nombres
y logotipos siguen siendo un catálogo global para torneos abiertos; los torneos
cerrados usan las identidades históricas descritas más abajo.

## Identidades históricas

Con los mismos secretos y variables del servidor, realiza una copia y detén
los escritores antes de aplicar la sexta migración y reiniciar:

```sh
.venv/bin/python -m flask --app server-flask/app.py init-snapshots
```

`006_team_snapshots.sql` añade `team_name_snapshot`, `team_logo_snapshot` y
`snapshot_created_at` en `tournament_teams`, y la vista
`tournament_team_identities`. Conserva IDs y claves externas; no duplica equipos,
partidos, sets ni clasificaciones. Si el rol de aplicación tiene permisos
explícitos, concede SELECT sobre la nueva vista desde el rol de migraciones.
El disparador de cierre necesita UPDATE sobre los tres campos de instantánea
en `tournament_teams`; concede esos permisos al rol de aplicación, sin permitir
que desactive disparadores ni sea propietario de las tablas.

Los torneos planificados y en curso muestran nombre y logotipo actuales.
Al completar o archivar un torneo abierto, se bloquean las filas de equipos
en orden de ID y un disparador captura todas las inscripciones en la misma
transacción que cambia el estado. Captura también los equipos sin partidos.
Archivar directamente congela la identidad en ese momento, incluso si hay
partidos pendientes. Completar sigue exigiendo resultados válidos. Completar
de nuevo o archivar un torneo completado nunca sobrescribe su instantánea.
Los cambios posteriores del catálogo no alteran nombres ni logos históricos.
Los disparadores rechazan cambios manuales de instantáneas y las protecciones
de autenticación, CSRF y resultados permanecen activas.

La migración rellena únicamente campos históricos que faltan en torneos ya
cerrados, usando la identidad actualmente disponible; el timestamp refleja la
captura, no la fecha original del cierre. No puede reconstruir un nombre o
logo antiguo que ya se perdió. No sobrescribe valores existentes y puede
repetirse. Ejecuta el comando Flask, no solo el SQL: prepara los assets locales
que necesita la migración. Los comandos antiguos de temporadas/programación
reinstalan también las protecciones de instantáneas cuando detectan la sexta
migración, para no debilitarlas al repetirse.

Los uploads ya tienen URLs únicas: se reutilizan sin copiar. Para los antiguos
logos autorizados de `/media/`, el cierre crea una copia WebP local validada,
con nombre derivado de su contenido, en `TEAM_LOGO_DIRECTORY`; varios torneos
con la misma imagen reutilizan esa copia. No se modifica la imagen original
ni la referencia del catálogo. No se aceptan rutas arbitrarias, archivos
simbólicos ni URLs externas. Si falta un logo, restaura su archivo o elimina
su referencia desde la administración antes de cerrar; el cierre falla sin
guardar instantáneas parciales.

Los archivos creados correctamente son inmutables y **no se borran** al reemplazar,
retirar o eliminar el logo actual. Esto evita carreras entre cierre y limpieza.
Solo se elimina un nuevo upload cuya operación de base de datos falla. Copias
materializadas antes de un fallo pueden quedar sin referencia y se conservan
de forma segura. Monitoriza espacio; no hay limpieza automática. Una limpieza
futura deberá ejecutarse con escritores detenidos y comprobar tanto `teams`
como `tournament_teams` antes de borrar cualquier archivo.

`backup.py` copia todo `TEAM_LOGO_DIRECTORY`, incluidos logos históricos y
originales materializados. Su recuperación restaura los mismos nombres y URLs;
la copia PostgreSQL incluye los campos históricos y sus protecciones. Las
copias anteriores a esta fase no contienen las nuevas instantáneas.
Tras restaurar una copia anterior a esta fase, aplica `init-snapshots` antes
de iniciar el servidor actualizado.

Las rutas de equipos, jornadas/resultados y clasificación utilizan una misma
vista para resolver identidad por torneo. Mantienen campos y estructuras
anteriores, añadiendo IDs y referencias públicas donde faltaban:
`team1Id`, `team2Id`, `team1Logo`, `team2Logo` en partidos públicos; `teamId` y
`logo` en clasificación. La lista de equipos conserva `id`, `name` y `logo`.
No se publican rutas del sistema de archivos. Las reglas de puntos y desempate
siguen siendo las mismas, usando el nombre histórico al ordenar empates.
La administración del catálogo `/api/admin/teams` muestra siempre identidad actual.

### Uso desde la administración

1. Entra en `/login` y abre «Temporadas y torneos».
2. Pulsa «Nueva temporada», introduce nombre, fechas opcionales y estado, y guarda.
3. Pulsa «Nuevo torneo», selecciona su temporada, introduce sus datos y guarda.
4. Selecciona equipos del catálogo y guarda cada inscripción. Crear un equipo
   en «Equipos» no lo inscribe automáticamente en ningún torneo.
5. Con el torneo seleccionado, crea jornadas, programa partidos y registra
   resultados mediante los controles existentes. La clasificación mostrada
   corresponde al torneo seleccionado, no necesariamente al torneo público.
6. Pulsa «Activar para el público» para seleccionarlo en el sitio público.
   Seleccionar otro torneo en el panel no cambia el sitio público por sí solo.

Los estados de la API son `planned`, `active`, `completed` y `archived`,
mostrados en español. Se permite avanzar de planificado a en curso, completado
o archivado; de en curso a completado o archivado; y de completado a archivado.
No se reabren competiciones cerradas. Completar un torneo requiere que todos
sus partidos estén finalizados con resultados válidos; archivarlo conserva
también los partidos pendientes. Una temporada solo se cierra cuando sus
torneos están cerrados. Torneos y temporadas cerrados no admiten cambios de
datos ni resultados. Corrige los resultados antes de cerrar el torneo.

Si la temporada tiene límites de fechas, los torneos deben proporcionar fechas
dentro de ellos. Las fechas locales de partidos deben estar dentro de los
límites del torneo, cuando existan. Se sigue usando `America/Havana` y UTC.
Nombres de temporadas únicos sin distinguir mayúsculas; nombres de torneos
únicos dentro de su temporada, de hasta 100 caracteres.

Solo un torneo tiene `isPublic=true`: un índice único y un bloqueo transaccional
serializan activaciones concurrentes. Otros torneos pueden seguir «En curso».
Cerrar el torneo público elimina su selección; no activa otro automáticamente.
Sin torneo público, las listas públicas predeterminadas están vacías.

### API de competiciones

Todas las rutas administrativas requieren sesión. Las escrituras requieren
`X-CSRF-Token` como las operaciones existentes. No existen rutas para eliminar
temporadas o torneos: se archivan para conservar su historial.

| Método y ruta | Operación |
| --- | --- |
| `GET/POST /api/admin/seasons` | Listar o crear temporadas |
| `PUT /api/admin/seasons/<id>` | Editar o cambiar estado |
| `GET/POST /api/admin/seasons/<id>/tournaments` | Listar o crear torneos de una temporada |
| `GET/POST /api/admin/tournaments` | Listar o crear torneos |
| `PUT /api/admin/tournaments/<id>` | Editar o cambiar estado |
| `POST /api/admin/tournaments/<id>/activate` | Seleccionar torneo público |
| `GET/POST /api/admin/tournaments/<id>/teams` | Listar o inscribir equipos |
| `DELETE /api/admin/tournaments/<id>/teams/<team_id>` | Retirar inscripción sin partidos asociados |

Creación de temporada: `{"name":"Temporada 2027","startDate":"2027-01-01","endDate":"2027-12-31","status":"planned"}`.
Creación de torneo: `{"seasonId":2,"name":"Torneo de verano","startDate":"2027-06-01","endDate":"2027-08-31","status":"planned"}`.
Inscripción: `{"teamId":1}`. Para cerrar, envía `{"status":"completed"}` o
`{"status":"archived"}` mediante PUT. Los IDs de ejemplo deben reemplazarse
por los devueltos por la API. Los errores utilizan 400, 401, 403, 404 o 409
según validación, sesión, CSRF, inexistencia o conflicto; mensajes en español.

Jornadas, programación, resultados y estadísticas administrativos aceptan
`?tournament_id=<id>`; si se omite, utilizan el torneo público. El panel lo
envía automáticamente. Los IDs de otras competiciones devuelven 404 y no
pueden trasladarse partidos, jornadas ni torneos a otra competición.
`/api/admin/teams` continúa gestionando el catálogo global.

Las rutas públicas conservan sus estructuras anteriores y admiten selección:

- `GET /api/tournaments`: catálogo público de torneos.
- `GET /api/tournaments/active`: torneo público; 404 si no hay selección.
- `GET /api/tournaments/<id>`: datos del torneo.
- `GET /api/tournaments/<id>/teams`: equipos inscritos.
- `GET /api/tournaments/<id>/jornadas`: calendario y resultados históricos.
- `GET /api/tournaments/<id>/standings`: clasificación histórica.
- `GET /api/teams`, `/api/jornadas` y `/api/standings`: torneo público por
  defecto; también aceptan `?tournament_id=<id>`.

Ejemplo de consulta pública de clasificación histórica:

```sh
curl 'http://127.0.0.1:3001/api/tournaments/1/standings'
```

## Sesiones y seguridad

Las sesiones de administración vencen dos horas después del inicio de
sesión; navegar no prolonga el límite. Las sesiones previas al inicio de
sesión duran 15 minutos. Al entrar se cambian el identificador y el token
CSRF. Cerrar sesión revoca el registro en PostgreSQL.

La cookie usa `HttpOnly`, `SameSite=Lax` y ruta `/`. En desarrollo HTTP no
usa `Secure`; con `APP_ENV=production` usa `Secure` y el nombre
`__Host-voli_session`. No se usan tokens en `localStorage`.

Todos los métodos distintos de GET, HEAD y OPTIONS requieren autenticación
y CSRF, excepto `/login`, que exige CSRF antes de comprobar credenciales.
Las rutas `/api/admin/` también están protegidas para lecturas. Los futuros
endpoints de escritura quedan cubiertos por esta política central: nunca
introduzcas operaciones que modifican datos mediante GET.

Las páginas privadas y respuestas de autenticación llevan `Cache-Control:
no-store`. La pantalla de acceso usa formularios HTML sin JavaScript ni
recursos externos. Las solicitudes del panel se envían al mismo origen.

El límite compartido es de 10 intentos por usuario y 30 por IP durante
15 minutos. Las respuestas no distinguen usuarios inexistentes, inactivos
o contraseñas incorrectas. Una IP compartida puede alcanzar el límite;
no se confía en cabeceras de IP reenviadas por defecto.

## Staging Railway + Neon

La preparación de despliegue, variables, volumen persistente, instalación nueva,
verificación HTTPS, rollback y checklist de redes cubanas están en
[docs/STAGING.md](docs/STAGING.md). El destino es una instalación nueva y vacía
en `voli_staging_2026` (PostgreSQL 18.6), sin importar registros ni media locales.
El comando optativo `init-staging --database-name voli_staging_2026
--empty-database-confirmed` crea el esquema completo transaccionalmente y rechaza
destinos ocupados. No se ejecuta automáticamente ni sin autorización remota.
El Dockerfile usa la raíz del repositorio;
no se han creado servicios ni desplegado. Staging requiere `STAGING=1`, conexión
directa con SSL verificado y `/data/team-logos` persistente. No poner secretos
en Git ni activar autodeploys antes de autorizar el primer despliegue.

## Producción

No despliegues con `python server-flask/app.py` ni `flask run`. Se incluye
Gunicorn, limitado por defecto a la interfaz local y pensado para un proxy HTTPS
de confianza. Para Railway consulta la guía de staging. No se ha realizado ningún despliegue.

Configura valores propios de tu instalación:

```sh
export APP_ENV=production
export DATABASE_URL='dbname=voleibolcuba'
export TRUSTED_HOSTS='liga.ejemplo.cu'
```

Variables requeridas en producción: `APP_ENV=production`, `DATABASE_URL`,
`FLASK_SECRET_KEY` y `TRUSTED_HOSTS`. El inicio falla si falta alguna o se
intenta activar depuración. `TRUSTED_HOSTS` contiene hosts separados por comas,
sin esquema, puerto ni `*`; un punto inicial permite subdominios de confianza.
`TRUST_PROXY` solo admite `0` o `1`. `TEAM_LOGO_DIRECTORY` debe apuntar a un
volumen persistente, accesible únicamente al usuario del servicio.

Después de instalar dependencias, aplicar las seis migraciones en orden y
configurar los secretos mediante tu gestor de servicios:

```sh
.venv/bin/python -m pip install -r server-flask/requirements-production.txt
.venv/bin/gunicorn --chdir server-flask --config server-flask/gunicorn.conf.py app:app
```

`requirements-production.txt` fija las dependencias de aplicación verificadas
con Python 3.12, sin paquetes ajenos presentes en el entorno de desarrollo.
Comprueba vulnerabilidades antes de publicar y actualiza este archivo junto
con la suite al aprobar nuevas versiones. No incluye hashes de distribución;
utiliza un índice de paquetes de confianza o artefactos verificados.

Gunicorn inicia dos procesos, escucha por defecto en `127.0.0.1:8000`, limita cabeceras,
recicla procesos y espera hasta 45 segundos por solicitud. No registra URLs,
cabeceras ni cuerpos mediante un registro de acceso. La aplicación registra
solo categorías de fallos, sin trazas de errores de PostgreSQL ni parámetros
SQL. No actives registros SQL detallados en producción. El registro del proxy
tampoco debe contener cookies, tokens CSRF, contraseñas o cuerpos de solicitudes.
Si se configura `PORT`, escucha en `0.0.0.0:$PORT` para la plataforma: usarlo solo
detrás del proxy controlado y no exponer el backend directamente a Internet.

El proxy debe terminar TLS, redirigir HTTP a HTTPS, conservar Host y limitar
el cuerpo a 3 MB, las conexiones, las solicitudes y los intentos contra `/login`.
Si usas `TRUST_PROXY=1`, debe **sobrescribir**, no concatenar sin control,
`X-Forwarded-For` y `X-Forwarded-Proto`, y ser el único proxy delante de Flask.
No expongas el puerto 8000. La aplicación rechaza HTTP en producción y hosts
no autorizados. La configuración de Gunicorn no confía por su cuenta en
cabeceras reenviadas; solo lo hace ProxyFix cuando se habilita explícitamente.

Requisitos de despliegue: certificados TLS y renovación, servidor PostgreSQL
compatible, Python y zonas horarias actualizados, usuario de servicio sin
privilegios, rol PostgreSQL de mínimo privilegio, supervisor con reinicio y
monitorización, almacenamiento persistente y copias verificadas fuera del
servidor. Usa un rol distinto para migraciones y otro para la aplicación.
El rol de ejecución no necesita CREATE DATABASE, superusuario ni permisos para
eliminar tablas. Las herramientas de recuperación usan un rol de mantenimiento.
Para PostgreSQL remoto configura `sslmode=verify-full` y la CA correspondiente.

Cada conexión se cierra al salir de su transacción y tiene 5 segundos para
conectar, 15 para cada sentencia, 5 para esperar bloqueos y 30 de inactividad
dentro de una transacción. Los fallos de servicio devuelven 503; los conflictos
de escritura, 409. No se utilizan conexiones globales compartidas entre procesos.
Las migraciones deben ejecutarse con tráfico detenido; si crece la base de
datos, revisa sus tiempos de ejecución antes de aplicarlas en producción.

Los formularios se limitan a 20 partes y 128 KB de memoria por campo; solicitudes normales,
a 64 KB. Las operaciones de equipos admiten 2 MB de imagen más 64 KB para el
formulario. Catálogos de temporadas, torneos y equipos administrativos admiten
`?limit=100&offset=0` (máximo 500, por defecto 500), manteniendo respuestas en
forma de lista. El panel actual está pensado para catálogos de hasta 500 entradas;
necesitará controles de paginación si se supera ese tamaño. Las consultas públicas
de jornadas y clasificación tienen un límite de 50 000 filas: si se supera,
se rechaza la consulta completa, sin publicar una clasificación parcial.

La cookie segura, HSTS, `nosniff`, bloqueo de marcos, política de referencias y
restricciones de cámara/micrófono/geolocalización se aplican sin recursos externos.
Todas las páginas tienen CSP estricta de origen propio, sin objetos incrustados.
Se retiró un script externo de Font Awesome que no se utilizaba: no cambian los
iconos ni el diseño y se elimina una solicitud externa innecesaria. No se
añadió ni cambió diseño frontend.

Proporciona también una `FLASK_SECRET_KEY` aleatoria y persistente desde
tu gestor de secretos. Sirve todo el sitio mediante HTTPS y un servidor
WSGI de producción; el servidor de desarrollo Flask no es para producción.
El proxy debe conservar la cabecera Host pública. Si un único proxy de
confianza termina HTTPS, configura `TRUST_PROXY=1` para aceptar sus cabeceras
`X-Forwarded-Proto` y `X-Forwarded-For`, y bloquea el acceso directo al backend.
No actives esa opción sin controlar el proxy.

Mantén frontend y API bajo el mismo origen y evita almacenar páginas
privadas en cachés del proxy. Limita también solicitudes en el proxy para
reducir abuso de la pantalla de acceso; los contadores de aplicación no
sustituyen la protección contra denegación de servicio.

## Mantenimiento

Con las mismas variables de entorno del servidor:

```sh
.venv/bin/python -m flask --app server-flask/app.py reset-admin-password --username administrador
.venv/bin/python -m flask --app server-flask/app.py prune-auth
```

El cambio de contraseña revoca todas las sesiones del administrador.
Programa `prune-auth` periódicamente, por ejemplo cada hora. Para desactivar
una cuenta, establece `administrators.active = FALSE`; el siguiente acceso
privado se rechaza.

Las sesiones ahora incluyen una huella HMAC de las credenciales. Un cambio de
contraseña invalida también una sesión creada durante una solicitud de acceso
concurrente al cambio. No se almacena el hash de contraseña en los datos de
sesión ni se devuelve la huella por API. Las sesiones antiguas sin esa huella
requieren iniciar sesión nuevamente tras esta actualización. Una operación
que ya estaba autorizada y ejecutándose no se cancela por cerrar sesión en
otra solicitud.

## Copias y recuperación

Se incluye `server-flask/backup.py`, sin dependencias adicionales. Requiere
`pg_dump` y `pg_restore` compatibles con la versión del servidor. Las copias
contienen cuentas y hashes de contraseñas: trátalas como secretos. Utiliza un
archivo `PGPASSFILE` de permisos 600 o un servicio libpq; evita contraseñas en
argumentos de terminal, Git o comandos de cron. El script no muestra mensajes
de herramientas que puedan contener credenciales y no pasa contraseñas por argv.

**Detén Gunicorn y otros escritores y espera a que terminen sus operaciones**
antes de copiar. La opción de confirmación no detiene el servidor: confirma
que tú lo has detenido. Esto hace coherentes la instantánea PostgreSQL y los
logotipos; una copia en línea de ambos por separado no garantiza esa coherencia.

```sh
export DATABASE_URL='dbname=voleibolcuba'
export TEAM_LOGO_DIRECTORY="$PWD/server-flask/instance/team-logos"
export BACKUP_ROOT='/ruta/privada/copias-voli'
umask 077
mkdir -p "$TEAM_LOGO_DIRECTORY" "$BACKUP_ROOT"
.venv/bin/python server-flask/backup.py backup \
  --logos "$TEAM_LOGO_DIRECTORY" \
  --output "$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ)" \
  --maintenance-confirmed
```

Cada copia tiene `database.dump`, `logos.tar.gz` y `manifest.json` con SHA-256.
Directorios 700, archivos 600. Si falla, se elimina la copia incompleta. Los
logotipos originales de `/media/` deben conservarse con la versión del código;
la copia de logotipos incluye uploads y copias históricas materializadas. Guarda también
la versión del código, requisitos instalados y configuración no secreta de
despliegue. Conserva secretos por separado en un gestor seguro.

Ejemplo manual equivalente para la base de datos, sin contraseña en argv:

```sh
PGSERVICE=voli_backup pg_dump --no-password --format=custom --file=database.dump
```

Este ejemplo presupone un servicio `voli_backup` en tu archivo libpq de
servicios y credenciales en `PGPASSFILE`. No uses un DATABASE_URL que contiene
contraseña como argumento `--dbname` en comandos manuales.

Recupera siempre primero a una **base nueva** y un directorio nuevo. El script
solo acepta nombres `voli_restore_...`, verifica las sumas, rechaza archivos
de logo no permitidos y nunca usa `--clean` ni sobrescribe la base de desarrollo:

```sh
.venv/bin/python server-flask/backup.py restore \
  --source "$BACKUP_ROOT/FECHA_DE_LA_COPIA" \
  --database-name voli_restore_verificacion \
  --logos /ruta/privada/logotipos-restaurados
```

Internamente crea la base con `TEMPLATE template0` y utiliza `pg_restore
--no-owner --no-privileges --single-transaction --exit-on-error`. Elimina
sesiones e intentos de acceso restaurados; conserva las cuentas y los hashes
de contraseñas. No recrea roles ni sus permisos: el responsable de
despliegue debe otorgarlos nuevamente. Las sumas detectan corrupción, no
sustituyen cifrado ni autenticidad frente a un atacante que controle la copia.

Comprueba equipos, jornadas, partidos, sets, cuentas, clasificaciones y logos
antes de utilizarla. Para la recuperación definitiva, con tráfico detenido,
apunta `DATABASE_URL` a la base verificada, `TEAM_LOGO_DIRECTORY` al directorio
restaurado y configura una nueva `FLASK_SECRET_KEY`. Reinicia y verifica antes
de abrir tráfico. Conserva intacta la base anterior hasta aprobar la recuperación.

Estrategia recomendada: copia diaria y antes de cada migración, cifrado fuera
del servidor, 7 copias diarias y 4 semanales como mínimo, alertas por fallos y
prueba mensual de recuperación. La retención requiere revisión manual o un
servicio de copias supervisado; el script no elimina copias antiguas. El tamaño
y la ventana de mantenimiento deben medirse. Si no resulta viable detener
escrituras, será necesario diseñar copias coordinadas de volumen o retención
de logotipos antes de automatizar una estrategia en línea.

## Historial y riesgos pendientes

Los resultados e identidades de torneos cerrados están protegidos por las
instantáneas de la fase 8.1. Los valores rellenados para torneos antiguos son
la información más temprana todavía disponible, no una reconstrucción de lo
que se perdió. La retención de archivos aumenta el uso de almacenamiento.

Antes de publicar: revisar configuración real
de proxy y TLS, probar con el rol PostgreSQL restringido, escanear las
dependencias fijadas, activar monitorización
y restaurar una copia en el entorno de destino. No se añadió MFA; acceso
administrativo debe usar contraseñas únicas y puede restringirse por VPN o proxy.
Los límites de aplicación no sustituyen protección de tráfico en el proxy.

## Sitio público móvil (fase 9A)

El sitio público conserva Flask, HTML, CSS y JavaScript nativos. El encabezado
identifica la liga; la navegación móvil queda fija abajo, sin un menú hamburguesa
redundante. Incluye torneo y temporada, próximo encuentro con fecha
confirmada, partidos pendientes, resultados con sets desplegables, clasificación,
equipos y selección de temporadas/torneos. Todos los textos son españoles.
Las fechas y la hora de consulta usan `America/Havana`.

La clasificación respeta directamente el orden y los valores del backend.
La API no define puntos de clasificación: se muestran **victorias**, sin
introducir un sistema de puntos. Se conserva la validación existente de sets
solo para presentar marcadores válidos; no se recalculan posiciones.
Los partidos originales sin fecha siguen visibles con «Fecha por confirmar»;
no se les inventa una fecha ni se destacan como futuros encuentros confirmados.
Las competiciones cerradas no anuncian partidos futuros, incluso si conservan
alguna programación pendiente en su historial.

La única extensión de backend es `GET /api/seasons`, alias de solo lectura del
catálogo de temporadas existente. Usa la misma paginación parametrizada
(`limit` máximo 500, `offset`), y solo expone identificador, nombre, fechas y
estado. No publica cuentas ni datos administrativos. Las rutas de escritura,
autenticación, CSRF, cabeceras y esquema PostgreSQL no cambian.

La carga normal hace dos consultas de catálogo y tres consultas para el torneo
seleccionado, todas públicas. Los catálogos grandes se recorren por páginas.
La selección de otro torneo consulta sus rutas explícitas de equipos, jornadas
y clasificación. Las respuestas históricas conservan nombres y logotipos
congelados, sin cruzarlos con el catálogo actual. Una caché en memoria de hasta
cinco torneos reutiliza datos abiertos durante 60 segundos y datos cerrados
durante la visita. La fecha/hora de consulta y la indicación de consulta anterior
son visibles; Actualizar y Reintentar fuerzan nuevas consultas. No hay caché
persistente de resultados, tokens en almacenamiento local ni solicitudes
administrativas desde el sitio público. Las solicitudes caducan a los 45 segundos.

No se añadió Bootstrap, Font Awesome, jQuery, fuentes descargables ni CDNs:
CSS propio y fuentes del sistema resultan suficientes. Los iconos SVG
pequeños están incluidos en el HTML. No hay scripts, estilos ni manejadores de
eventos en línea. Las imágenes reservan espacio, usan carga diferida fuera del
encuentro destacado y dejan iniciales legibles si faltan o fallan.

Los cinco archivos `media/preview-*.webp` son copias de 128 px de los logotipos
originales; no sustituyen originales, archivos subidos ni instantáneas históricas.
Para regenerarlos usando Pillow, ya incluido en los requisitos:

```sh
.venv/bin/python scripts/optimize-public-logos.py
```

El ajuste visual posterior usa tarjetas con radio de 16 px y navegación móvil
inferior fija con radio de 20 px: Inicio, Partidos, Tabla y Equipos. Se reserva
espacio inferior, incluida el área segura del dispositivo, para que el último
control no quede tapado. Historial sigue disponible mediante «Cambiar torneo»; en
escritorio se conserva la navegación superior. La pestaña seleccionada usa
`aria-current` y sigue los cambios de ancla, incluido Atrás/Adelante.
El hero conserva el fondo azul oscuro y los bordes redondeados de la referencia,
con VOLI, el icono de voleibol y «La pasión se vive en la cancha». Mantiene los
datos reales del torneo; el próximo partido queda separado en blanco, con
acceso al calendario. Al seleccionar una competición anterior, la etiqueta
cambia a «Historial de temporadas».
Los cuatro SVG de navegación son Lucide (house, calendar-days, trophy, shield),
revisión `a04f228cd01185e09c188b7227b9600c08c565ec`, licencia ISC incluida en
`licenses/lucide-icons.txt`. Están incrustados localmente: 1438 bytes de SVG,
464 bytes gzip medidos juntos, incluidos en el peso HTML y sin solicitudes extra.
El icono volleyball de la marca procede de la misma revisión y licencia.

Mediciones actualizadas del 9 de octubre de 2026, con los datos reales de la liga:

| Recurso | Bytes sin comprimir | Bytes gzip, nivel 9 |
| --- | ---: | ---: |
| HTML | 12526 | 3156 |
| CSS | 16357 | 3760 |
| JavaScript | 20574 | 6220 |
| Imágenes inicialmente solicitadas, incluido favicon | 21830 | WebP ya comprimido; favicon SVG local |
| Fuentes/iconos externos | 0 | 0 |

HTML + CSS comprimidos: 6916 bytes, por debajo del objetivo de 70 KB.
JavaScript comprimido: 6220 bytes, por debajo de 50 KB. Las imágenes y fuentes
también cumplen los objetivos de 100 KB y 25 KB para los datos actuales.
Estas cifras gzip se midieron sobre los archivos, no sobre respuestas comprimidas:
el servidor Flask de desarrollo envía `Content-Encoding: identity`.
La transferencia real medida fue de 82971 bytes, incluidas cabeceras,
API e imágenes, en 14 solicitudes iniciales. El favicon local de voleibol evita
la petición automática a `/favicon.ico`, que antes devolvía 404. Los archivos estáticos mantienen
ETag/revalidación (`Cache-Control: no-cache`); los logotipos subidos conservan
su caché inmutable existente. En producción, habilita compresión en el proxy
HTTPS y vuelve a medir sin cambiar las protecciones de páginas privadas.

Prueba Slow 3G: tres visitas independientes con caché desactivada, viewport
390 × 844, CDP de Chromium, 400 ms de latencia, 400 kbit/s de descarga/subida
y CPU ralentizada cuatro veces. Datos utilizables en 2637–2638 ms; primer
contenido visible en 1580–1592 ms; recursos iniciales estabilizados en 3819–3846 ms;
desplazamiento de diseño acumulado (CLS) 0,00073.
No es una medición de una red cubana real ni de un teléfono físico.
Logotipos históricos o futuras imágenes subidas pueden aumentar la transferencia:
no se alteran automáticamente los archivos históricos para cumplir un presupuesto.

Verificación visual y funcional en Chromium y WebKit: 320, 360, 375, 390, 430,
768, 1024 y 1440 px, sin desbordamiento horizontal, incluidas estadísticas
desplegadas y nombres largos. Se probaron navegación, teclado, selección,
instantáneas, ausencia/fallo de logotipos, datos vacíos, error HTTP 503 y reintento.
WebKit 27.2 emite dos avisos de CSP al construir los selectores nativos, reproducidos
en un documento mínimo sin JavaScript ni CSS del sitio; funcionan correctamente.
Playwright genera otro aviso al inyectar su estilo de sincronización de capturas.
La prueba registra estos avisos por separado; no se relajó `style-src 'self'`.
Queda pendiente probar Safari/Chrome en teléfonos físicos, versiones antiguas
y conexiones cubanas reales. JavaScript es necesario para consultar las APIs;
sin él se conserva un aviso español, pero no resultados renderizados por servidor.

La comprobación opcional de navegador usa Playwright 1.64.0 (Apache-2.0), solo
para desarrollo, con **cero bytes** añadidos al sitio. No es un requisito de
producción. Puede instalarse fuera del repositorio para reproducirla:

```sh
npm install --prefix /tmp/voli-public-qa playwright@1.64.0
node /tmp/voli-public-qa/node_modules/playwright/cli.js install webkit
NODE_PATH=/tmp/voli-public-qa/node_modules PUBLIC_QA_URL=http://127.0.0.1:3002 node tests/public-browser.cjs
```

El script usa Chrome instalado en macOS; `CHROME_PATH` permite indicar otro
ejecutable. `PUBLIC_QA_OUTPUT` cambia la carpeta de capturas/informe, por defecto
`/private/tmp/voli-phase9a-qa`. Nunca guarda capturas en el repositorio ni modifica
la base de datos: los escenarios históricos simulados interceptan únicamente
GETs en el navegador. Para revisar localmente, sigue la configuración inicial
de este README y ejecuta con tus variables de entorno:

```sh
PORT=3002 .venv/bin/python server-flask/app.py
```

La investigación de la fase 9B confirmó que la prueba anterior esperaba el
evento `load` completo antes de comprobar si los datos eran utilizables. Un
recurso no esencial pendiente puede impedir ese evento; una regresión con una
imagen retenida reproduce el timeout mientras la clasificación sigue disponible.
El timeout transitorio original no tenía diagnóstico de red y no volvió a
reproducirse en las visitas normales: no es posible atribuirlo retrospectivamente
a una petición concreta ni afirmar que lo causó el favicon.

La prueba conserva la misma simulación Slow 3G y usa un navegador independiente
para las mediciones. Espera `DOMContentLoaded` y datos visibles dentro de un
presupuesto total de 5 segundos; exige primer contenido visible en 3 segundos,
recursos iniciales completos en 10 segundos, CLS menor que 0,1 y los presupuestos
de transferencia de 70/50/25/100 KiB. No se amplió el timeout anterior de 30 segundos.
Los bytes se miden después de completar las peticiones iniciales, en vez de
esperar un segundo fijo. Los informes `slow3g-*-network.json` incluyen tiempos,
estados HTTP, recursos pendientes y errores JavaScript; las fallas también guardan
`slow3g-*-failure.json` y un informe parcial. No registran cookies, credenciales
ni cabeceras de autenticación. Esta corrección no cambia el diseño ni las APIs.

Abre `http://127.0.0.1:3002`. No se necesita migración para esta fase. Las suites
de la fase 9A pasaron: 109 pruebas Python. Tras el ajuste visual pasan las 27
pruebas JavaScript y las comprobaciones de navegador; no cambió código Python.
Los recuentos y huellas de
equipos, jornadas, partidos, sets, temporadas, torneos e inscripciones antes y
después de las pruebas coinciden. El panel de administración no se rediseñó.

## Pruebas

El panel administrativo y el inicio de sesión comparten ahora la identidad
visual pública: marca VOLI, icono de voleibol, azul oscuro, botones azules y
controles redondeados. En teléfonos, el panel usa cinco pestañas inferiores
(Panel, Equipos, Torneos, Jornadas y Resultados); desde 960 px usa una barra
lateral. La navegación conserva todas las herramientas existentes y sigue
las anclas con `aria-current`. No cambia la autenticación, CSRF ni los datos.

Comprobación visual opcional del panel, con Playwright instalado por separado:

```sh
NODE_PATH=/ruta/a/node_modules ADMIN_QA_URL=http://127.0.0.1:3002 node tests/admin-browser.cjs
```

Esta prueba sirve una plantilla y scripts autenticados solo dentro del navegador
de pruebas e intercepta todas las APIs con datos ficticios. No usa credenciales
reales ni modifica PostgreSQL. Comprueba formularios, diálogos, protección visual
de resultados finalizados, envío de resultados con CSRF y navegación a 320,
390, 768, 1024 y 1440 px en Chromium y WebKit.

Verificación final de la fase 9B: 110 pruebas Python y 31 pruebas JavaScript
aprobadas, más las suites públicas y administrativas de Chromium y WebKit.
Las pruebas PostgreSQL siguen usando esquemas aislados. Las medidas Slow 3G
se ejecutan separadas de otros procesos de prueba para evitar competencia de CPU.

```sh
node --test tests/*.test.cjs
.venv/bin/python -m unittest discover -s server-flask -p 'test_*.py'
```

Las pruebas usan conexiones simuladas y no modifican datos reales. Cubren
inicio y cierre de sesión, credenciales incorrectas, caducidad, CSRF,
revocación, límites de intentos, cookies de producción, rutas privadas y
públicas, validación de resultados y protección de archivos. También cubren
CRUD de equipos, duplicados, imágenes inválidas, CSRF, archivos y rechazo
de eliminaciones con partidos asociados.
Las pruebas de programación cubren jornadas, partidos, duplicados, protección
de resultados, calendario público, autenticación, CSRF y cambios de horario
de Cuba. Las pruebas PostgreSQL usan únicamente esquemas temporales aislados.
`tests/business-rules.json` contiene casos compartidos entre Python y
JavaScript para comprobar que validación y clasificación coinciden.

Para probar también las sesiones reales de PostgreSQL:

```sh
AUTH_TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m unittest discover -s server-flask -p 'test_*.py'
```

Esta prueba necesita permiso para crear esquemas. Crea un esquema temporal
con un nombre aleatorio y lo elimina al terminar, sin tocar las tablas de
la liga ni las cuentas reales.

Las pruebas de competiciones cubren temporadas, torneos, inscripciones,
jornadas por torneo, equipos no inscritos, fechas, clasificaciones independientes,
historial, compatibilidad pública, migraciones repetidas, autenticación, CSRF,
activaciones concurrentes y protección de competiciones cerradas.

Las pruebas adicionales verifican configuración de producción, HTTPS y Host,
cabeceras, límites de formularios, paginación, redacción de errores y copias.
La prueba de recuperación crea una base `voli_restore_test_<aleatorio>` en el
mismo servidor, compara registros y logotipos y la elimina al terminar. Necesita
un rol de pruebas con CREATE DATABASE; nunca sobreescribe la liga. No ejecutes
esta prueba con el rol restringido de la aplicación. Las pruebas SQL temporales
pueden aparecer en una copia tomada durante la suite; las verificaciones ignoran
esos esquemas y el destino aislado se elimina al terminar.

Referencias de configuración: [seguridad de Flask](https://flask.palletsprojects.com/en/stable/web-security/),
[proxy de confianza](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/)
y [pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html).
