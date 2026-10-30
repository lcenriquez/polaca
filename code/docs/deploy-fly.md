# Guía de despliegue de la demo en Fly.io

Comandos exactos, en orden, desde la raíz del repo. Requisitos: `flyctl`
instalado, sesión iniciada (`fly auth login`) y los valores reales de los
secretos a la mano (nunca se escriben en el repo ni en archivos del repo).

Los secretos **solo** se cargan con `fly secrets set`. Nunca van en
`fly.toml`, en el `Dockerfile`, en `.env` commiteado ni en la imagen.

## 1. Crear la app sin desplegar

```bash
fly launch --no-deploy
```

Acepta el `fly.toml` del repo cuando lo pregunte y confirma la región
`qro`. Si el nombre `polaca-demo` está tomado, elige otro y úsalo en
`--app <nombre>` en los pasos siguientes (o exporta `FLY_APP=<nombre>`
para el script de datos).

## 2. Crear el volumen (1 GB, región qro)

```bash
fly volumes create polaca_data --size 1 --region qro --app polaca-demo
```

El nombre `polaca_data` debe coincidir con `[[mounts]] source` en
`fly.toml`. Aquí vivirá SQLite; sin volumen, la base se pierde en cada
despliegue.

## 3. Cargar los secretos

```bash
fly secrets set META_API_KEY=<valor-real> --app polaca-demo
fly secrets set ADMIN_TOKEN=<valor-real> --app polaca-demo
```

Sustituye `<valor-real>` en tu terminal; no lo guardes en ningún archivo
del repo. Verifica solo los nombres (nunca imprime valores):

```bash
fly secrets list --app polaca-demo
```

## 4. Desplegar

```bash
fly deploy --app polaca-demo
```

Esto construye la imagen del `Dockerfile` (sin datos ni secretos) y deja
una sola máquina siempre encendida (`min_machines_running = 1`, sin
auto-stop, porque SQLite vive en el volumen y el agente corre en segundo
plano).

## 5. Subir los datos al volumen

```bash
bash scripts/subir_datos.sh
```

Copia `datos/auditor.db` y `datos/raw/` a `/data` con `fly ssh sftp`.
No sube `datos/cache` (se regenera) ni `datos/evidencia` (fotos
ciudadanas). Si tu app se llama distinto: `FLY_APP=<nombre> bash scripts/subir_datos.sh`.

## 6. Verificar

```bash
fly status --app polaca-demo
fly logs --app polaca-demo
curl -i https://polaca-demo.fly.dev/
```

Debe responder `200` en `/` (el health check de `fly.toml` apunta ahí).
Abre también la URL en el navegador y confirma que se ven los datos.

## Problemas frecuentes

- **La app arranca sin datos**: el volumen no estaba montado o no se
  corrió el paso 5. Revisa `fly volumes list --app polaca-demo`.
- **La máquina se duerme**: alguien cambió `auto_stop_machines`;
  debe quedar en `"off"` con `min_machines_running = 1`.
- **Falta un secreto**: `fly secrets list` muestra nombres; vuelve al
  paso 3. Jamás lo pongas en `fly.toml` para "probar rápido".
