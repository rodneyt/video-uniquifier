# Video Uniquifier

Monorepo para procesamiento de videos y evasión de contenido duplicado en TikTok/Instagram.

## Arquitectura

- **web**: Frontend en Next.js 14 (App Router), Tailwind CSS y shadcn/ui. (Export estático)
- **api**: Backend FastAPI en Python 3.12, SQLAlchemy, JWT Auth. Sube URLs prefirmadas a Cloudflare R2 y encola jobs.
- **worker**: Worker en Python 3.12, FFmpeg 6 y RQ (Redis Queue). Procesa el video, le aplica filtros únicos en un solo pase de FFmpeg y sube el resultado a R2.
- **shared**: Modelos y esquemas compartidos.
- **assets**: Contiene los LUTs y overlays.

## Setup Local

1. Instalar Docker y Docker Compose.
2. Crear un archivo `.env` en la raíz (puedes basarte en el `docker-compose.yml` para los valores default, excepto R2 que debes proveer).
   ```bash
   R2_ACCESS_KEY="tu_key"
   R2_SECRET="tu_secret"
   R2_BUCKET="tu_bucket"
   R2_ENDPOINT="https://<tu_account_id>.r2.cloudflarestorage.com"
   ```
3. Levantar los servicios:
   ```bash
   docker-compose up --build
   ```
4. Poblar la base de datos con el usuario demo:
   ```bash
   # Dentro del contenedor de la API o localmente si tienes Python configurado:
   docker-compose exec api python seed.py
   ```
5. El backend estará en `http://localhost:8000`.

## Configuración de R2 (Cloudflare)

1. Crea un bucket en Cloudflare R2.
2. Ve a R2 -> Manage R2 API Tokens y crea un token con permisos de "Edit".
3. Copia el Endpoint, Access Key y Secret Key y ponlos en las variables de entorno de Render o tu `.env`.
4. Importante: Configura los CORS en tu bucket R2 para permitir llamadas `PUT` desde el dominio de tu frontend.

## Despliegue en Render (Un click)

Haz click en el siguiente botón para desplegar automáticamente la API, Worker, Redis y PostgreSQL usando Render Blueprint.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

El frontend en Next.js se debe desplegar como un Static Site en Render, apuntando al directorio `web` y usando el build command `npm run build` y el publish directory `web/out`.
