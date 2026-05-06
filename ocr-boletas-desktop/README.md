# OCR Boletas Desktop

Aplicacion de escritorio profesional en Python para procesar PDFs escaneados de boletas operativas mediante OCR. Permite cargar un PDF, visualizar la primera pagina, extraer datos con Tesseract, corregirlos en un formulario editable y exportarlos a JSON.

No es una aplicacion web y no usa Streamlit. La interfaz esta construida con PySide6.

## Requisitos

- Windows 10/11 recomendado.
- Python 3.11 o superior.
- Tesseract OCR instalado.
- Dependencias Python listadas en `requirements.txt`.

## Instalacion de Python

1. Descargue Python desde https://www.python.org/downloads/windows/
2. Durante la instalacion marque `Add python.exe to PATH`.
3. Verifique la instalacion:

```powershell
python --version
```

Debe mostrar Python 3.11 o superior.

## Crear entorno virtual

Desde la carpeta del proyecto:

```powershell
cd "C:\Users\rgarcia\Documents\New project\ocr-boletas-desktop"
python -m venv venv
.\venv\Scripts\activate
```

## Instalar dependencias

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

## Instalar Tesseract OCR en Windows

1. Instale Tesseract OCR para Windows.
   Una opcion comun es el instalador de UB Mannheim:
   https://github.com/UB-Mannheim/tesseract/wiki
2. Durante la instalacion puede incluir paquetes de idioma adicionales, por ejemplo `spa`.
3. Si el instalador ofrece agregar Tesseract al PATH, active esa opcion.
4. Verifique:

```powershell
tesseract --version
```

## Configurar ruta de Tesseract

La aplicacion intenta detectar Tesseract en estas rutas comunes:

- `C:\Program Files\Tesseract-OCR\tesseract.exe`
- `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

Si Tesseract esta en otra ubicacion, configure la variable de entorno antes de ejecutar:

```powershell
$env:TESSERACT_CMD="C:\Ruta\A\Tesseract-OCR\tesseract.exe"
python main.py
```

Tambien puede editar `config/settings.py` y ajustar `TESSERACT_CMD`.

## Ejecutar la app

Con el entorno virtual activo:

```powershell
cd "C:\Users\rgarcia\Documents\New project\ocr-boletas-desktop"
python main.py
```

## Uso paso a paso

1. Abra la aplicacion con `python main.py`.
2. Presione `Cargar PDF`.
3. Seleccione el PDF escaneado.
4. Revise la previsualizacion de la primera pagina.
5. Presione `Procesar OCR`.
6. Espere a que la barra de estado indique `OCR completado`.
7. Revise y corrija la seccion `Encabezado`.
8. Revise o edite `tabla_productos` con `Agregar producto` o `Eliminar producto seleccionado`.
9. Revise o edite `plan_de_cargue`. Esta tabla siempre tiene 10 compartimientos.
10. Abra la pestana `OCR completo` para ver el texto detectado.
11. Abra la pestana `Vista JSON` para revisar el JSON final.
12. Use `Copiar JSON al portapapeles` si necesita pegarlo en otro sistema.
13. Presione `Exportar JSON` para guardar el archivo.

## Generar un .exe con PyInstaller

Con el entorno virtual activo:

```powershell
pyinstaller --noconfirm --windowed --name OCRBoletas main.py
```

El ejecutable se generara en:

```text
dist\OCRBoletas\OCRBoletas.exe
```

Si desea un solo archivo:

```powershell
pyinstaller --noconfirm --onefile --windowed --name OCRBoletas main.py
```

Nota: el .exe no instala Tesseract. Tesseract debe estar instalado en la computadora destino o debe configurarse su ruta.

## Estructura del proyecto

```text
ocr-boletas-desktop/
├── main.py
├── requirements.txt
├── README.md
├── .gitignore
├── core/
│   ├── __init__.py
│   ├── pdf_utils.py
│   ├── image_processing.py
│   ├── ocr_engine.py
│   ├── plan_cargue_extractor.py
│   ├── parser.py
│   ├── json_exporter.py
│   └── validators.py
├── ui/
│   ├── __init__.py
│   └── main_window.py
├── config/
│   ├── __init__.py
│   └── settings.py
├── output/
├── samples/
└── logs/
```

## Responsabilidad de modulos

- `main.py`: inicia `QApplication`, crea `MainWindow` y muestra la ventana.
- `ui/main_window.py`: contiene la interfaz, botones, visor PDF, encabezado editable, tabla_productos, plan_de_cargue, OCR completo y preview JSON.
- `core/pdf_utils.py`: valida, abre y renderiza PDFs con PyMuPDF.
- `core/image_processing.py`: mejora imagen con OpenCV para OCR.
- `core/ocr_engine.py`: encapsula pytesseract y verifica Tesseract.
- `core/plan_cargue_extractor.py`: detecta la grilla del PLAN DE CARGUE y ejecuta OCR por celda para llenar 10 compartimientos.
- `core/parser.py`: construye la estructura `encabezado`, `tabla_productos` y `plan_de_cargue`.
- `core/json_exporter.py`: normaliza, genera y guarda JSON UTF-8 indentado.
- `core/validators.py`: valida campos importantes antes de exportar.
- `config/settings.py`: centraliza idioma OCR, DPI, rutas y configuracion global.

## Ajustes si el OCR no detecta bien

1. Cambiar idioma OCR en `config/settings.py`:

```python
OCR_LANGUAGE = "eng+spa"
```

2. Ajustar DPI de renderizado:

```python
PDF_RENDER_DPI = 220
```

3. Ajustar preprocesamiento en `core/image_processing.py`.
   Los puntos principales son `improve_contrast`, `denoise` y `threshold_image`.

4. Ajustar patrones del parser en `core/parser.py`.
   Revise `_extract_header`, `extract_tabla_productos` y las funciones de normalizacion.

5. Ajustar palabras clave de productos en `core/parser.py`.
   Modifique `PRODUCT_KEYWORDS` si aparecen nuevos combustibles o nombres comerciales.

6. Ajustar extraccion del `PLAN DE CARGUE` en `core/plan_cargue_extractor.py`.
   Esta logica detecta la tabla visualmente y reconstruye productos por compartimiento.

## Estructura JSON final

El JSON exportado contiene solo estas secciones principales:

```json
{
  "encabezado": {},
  "tabla_productos": [],
  "plan_de_cargue": {
    "compartimientos": []
  }
}
```

`plan_de_cargue.compartimientos` siempre contiene 10 filas, numeradas del `"1"` al `"10"`. Si no se detecta informacion para un compartimiento, sus campos quedan como string vacio.

## Errores comunes

### Tesseract no esta instalado o no se encontro

Instale Tesseract y verifique `tesseract --version`. Si no esta en PATH, configure `TESSERACT_CMD`.

### El OCR devuelve texto vacio

El PDF puede tener baja resolucion, estar muy inclinado o tener poco contraste. Pruebe aumentar `PDF_RENDER_DPI` o ajustar `core/image_processing.py`.

### No se puede abrir el PDF

El archivo puede estar corrupto, protegido o no ser un PDF real. Pruebe abrirlo manualmente en un lector PDF.

### No se puede guardar JSON

Seleccione una carpeta donde el usuario tenga permisos de escritura.

## Preparacion futura

La arquitectura separa UI, OCR, parser y exportacion para poder agregar despues:

- Monitoreo automatico de carpeta.
- Procesamiento por lotes.
- Envio del JSON a una API.
- Exportacion a Excel.
- Historial de documentos procesados.
- Soporte para multiples paginas.
- Configuracion visual de ruta de Tesseract.
