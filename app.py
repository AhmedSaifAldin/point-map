import collections
import json
import os
import re
from flask import (
    Flask,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

app = Flask(__name__)
app.secret_key = 'your_secret_key_here_change_this'
UPLOAD_FOLDER = '.'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

USERNAME = 'admin'
PASSWORD = '123'

CUSTOM_POINTS_FILE = os.path.join(UPLOAD_FOLDER, 'custom_points_temp.json')


def get_real_coordinates_from_url(short_url):
  if not short_url or 'http' not in short_url:
    return None, None

  match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', short_url)
  if match:
    return float(match.group(1)), float(match.group(2))

  match_q = re.search(r'q=(-?\d+\.\d+),(-?\d+\.\d+)', short_url)
  if match_q:
    return float(match_q.group(1)), float(match_q.group(2))

  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
          'AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/120.0.0.0 Safari/537.36'
      )
  }
  try:
    response = requests.get(
        short_url, headers=headers, allow_redirects=True, timeout=8
    )
    final_url = response.url

    match_final = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
    if match_final:
      return float(match_final.group(1)), float(match_final.group(2))

    match_q_final = re.search(r'q=(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
    if match_q_final:
      return float(match_q_final.group(1)), float(match_q_final.group(2))

    match_body = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', response.text)
    if match_body:
      return float(match_body.group(1)), float(match_body.group(2))

  except Exception:
    pass

  return None, None


def load_custom_points():
  if os.path.exists(CUSTOM_POINTS_FILE):
    try:
      with open(CUSTOM_POINTS_FILE, 'r', encoding='utf-8') as f:
        points = json.load(f)
        for p in points:
          if 'neighborhood' not in p:
            p['neighborhood'] = '-'
        return points
    except Exception:
      return []
  return []


def save_custom_point(
    lat, lon, note, url='#', project='  ', neighborhood='-'
):
  points = load_custom_points()
  points.append({
      'lat': lat,
      'lon': lon,
      'note': note,
      'url': url,
      'project': project,
      'neighborhood': neighborhood,
  })

  try:
    with open(CUSTOM_POINTS_FILE, 'w', encoding='utf-8') as f:
      json.dump(points, f, ensure_ascii=False)
  except Exception:
    pass


def get_available_shapefiles():
  shapes_dir = os.path.join(UPLOAD_FOLDER, 'shapes')
  shapefiles_list = []
  seen_names = set()
  if os.path.exists(shapes_dir):
    for root, dirs, files in os.walk(shapes_dir):
      for file in files:
        if file.endswith('.shp'):
          rel_path = os.path.relpath(os.path.join(root, file), shapes_dir)
          folder_name = os.path.basename(root)
          
          if folder_name and folder_name != 'shapes':
            display_name = folder_name
          else:
            proj_name = os.path.splitext(file)[0]
            display_name = proj_name.replace('_', ' ').replace('&', ' & ').title()

          # إضافة العنصر فقط إذا لم يتم إضافته مسبقاً
          if display_name not in seen_names:
            seen_names.add(display_name)
            shapefiles_list.append({
                'id': rel_path.replace('\\', '/'),
                'name': display_name,
            })
  return shapefiles_list


def load_shapefile_as_geojson(proj_id):
  if not proj_id or proj_id == 'ALL':
    return None
  shapes_dir = os.path.join(UPLOAD_FOLDER, 'shapes')
  shp_path = os.path.join(shapes_dir, proj_id)
  if not os.path.exists(shp_path):
    for root, dirs, files in os.walk(shapes_dir):
      for file in files:
        if file.endswith('.shp') and (
            proj_id in file or proj_id in os.path.relpath(root, shapes_dir)
        ):
          shp_path = os.path.join(root, file)
          break
  if os.path.exists(shp_path):
    try:
      gdf = gpd.read_file(shp_path)
      if gdf.crs != 'EPSG:4326':
        gdf = gdf.to_crs(epsg=4326)
      return json.loads(gdf.to_json())
    except Exception as e:
      print('Error loading shapefile:', e)
  return None


def enrich_locations_with_shape_data(locations, proj_id):
  shapes_dir = os.path.join(UPLOAD_FOLDER, 'shapes')
  gdfs = []
  if proj_id and proj_id != 'ALL':
    shp_path = os.path.join(shapes_dir, proj_id)
    if not os.path.exists(shp_path):
      for root, dirs, files in os.walk(shapes_dir):
        for file in files:
          if file.endswith('.shp') and (
              proj_id in file or proj_id in os.path.relpath(root, shapes_dir)
          ):
            shp_path = os.path.join(root, file)
            break
    if os.path.exists(shp_path):
      try:
        gdf = gpd.read_file(shp_path)
        if gdf.crs != 'EPSG:4326':
          gdf = gdf.to_crs(epsg=4326)
        gdfs.append(gdf)
      except Exception:
        pass
  else:
    if os.path.exists(shapes_dir):
      for root, dirs, files in os.walk(shapes_dir):
        for file in files:
          if file.endswith('.shp'):
            try:
              gdf = gpd.read_file(os.path.join(root, file))
              if gdf.crs != 'EPSG:4326':
                gdf = gdf.to_crs(epsg=4326)
              gdfs.append(gdf)
            except Exception:
              pass

  for loc in locations:
    lat = loc.get('lat')
    lon = loc.get('lon')
    round_id_val = '-'
    if lat and lon:
      pt = Point(lon, lat)
      for gdf in gdfs:
        matched = gdf[gdf.contains(pt)]
        if not matched.empty:
          props = matched.iloc[0]
          for col in props.index:
            if any(
                k in col.lower() for k in ['round_id', 'roundid', 'round']
            ):
              val = props[col]
              if pd.notna(val) and str(val).strip() != '':
                round_id_val = str(val)
                break
          if round_id_val == '-':
            for col in props.index:
              if any(k in col.lower() for k in ['id', 'name', 'title']):
                val = props[col]
                if pd.notna(val) and str(val).strip() != '':
                  round_id_val = str(val)
                  break
          if round_id_val != '-':
            break
    loc['round_id'] = round_id_val
    if 'neighborhood' not in loc:
      loc['neighborhood'] = '-'
  return locations


def get_resolved_data(file_path):
  try:
    df = pd.read_excel(file_path)
  except Exception:
    try:
      df = pd.read_csv(file_path)
    except Exception:
      return []

  if df.empty or len(df.columns) == 0:
    return []

  resolved_data = []

  for index, row in df.iterrows():
    url_found = ''
    extracted_text = ''
    lat, lon = None, None
    project_name = 'مشروع عام'
    neighborhood_name = '-'

    for col in df.columns:
      val = row[col]
      if pd.isna(val):
        continue
      val_str = str(val).strip()

      col_lower = str(col).lower()
      if 'مشروع' in col_lower or 'project' in col_lower:
        if val_str:
          project_name = val_str
        continue

      if 'حي' in col_lower or 'neighborhood' in col_lower or 'district' in col_lower:
        if val_str:
          neighborhood_name = val_str
        continue

      try:
        num_val = float(val_str)
        if 20 < num_val < 35 and not lat:
          lat = num_val
          continue
        elif 35 < num_val < 60 and not lon:
          lon = num_val
          continue
      except ValueError:
        pass

      if 'http' in val_str or 'goo.gl' in val_str or 'maps' in val_str:
        url_found = val_str
      else:
        if len(val_str) > 0 and not extracted_text:
          extracted_text = val_str

    note = extracted_text if extracted_text else f'موقع {index + 1}'

    if url_found and (not lat or not lon):
      lat, lon = get_real_coordinates_from_url(url_found)

    if not lat or not lon:
      lat, lon = 24.7136, 46.6753

    resolved_data.append({
        'lat': lat,
        'lon': lon,
        'url': url_found if url_found else '#',
        'note': note,
        'project': project_name,
        'neighborhood': neighborhood_name,
    })

  return resolved_data


@app.route('/login', methods=['GET', 'POST'])
def login():
  error = ''
  if request.method == 'POST':
    if (
        request.form['username'] == USERNAME
        and request.form['password'] == PASSWORD
    ):
      session['logged_in'] = True
      return redirect(url_for('index'))
    else:
      error = 'اسم المستخدم أو كلمة المرور غير صحيحة!'

  login_template = """<!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>تسجيل الدخول - نظام الخريطة</title>
        <link rel="icon" href="{{ url_for('static', filename='icon.png') }}" type="image/png">
        <style>
            body { margin: 0; padding: 0; font-family: Tahoma, sans-serif; background: #f4f7f6; display: flex; justify-content: center; align-items: center; height: 100vh; }
            .login-card { background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); width: 320px; box-sizing: border-box; }
            h2 { color: #2c3e50; font-size: 20px; margin-top: 0; text-align: center; margin-bottom: 20px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 13px; color: #34495e; }
            input[type="text"], input[type="password"] { width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 6px; box-sizing: border-box; font-size: 14px; background: #fafafa; }
            button { background-color: #27ae60; color: white; border: none; padding: 12px; border-radius: 6px; cursor: pointer; font-size: 14px; width: 100%; font-weight: bold; transition: background 0.3s; }
            button:hover { background-color: #219653; }
            .error { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 6px; font-size: 12px; margin-bottom: 15px; border-right: 4px solid #dc3545; text-align: center; }
        </style>
    </head>
    <body>
        <div class="login-card">
            <h2>تسجيل الدخول</h2>
            {% if error %}
                <div class="error">{{ error }}</div>
            {% endif %}
            <form method="POST">
                <div class="form-group">
                    <label for="username">اسم المستخدم:</label>
                    <input type="text" id="username" name="username" required>
                </div>
                <div class="form-group">
                    <label for="password">كلمة المرور:</label>
                    <input type="password" id="password" name="password" required>
                </div>
                <button type="submit">دخول</button>
            </form>
        </div>
    </body>
    </html>
    """
  return render_template_string(login_template, error=error)


@app.route('/logout')
def logout():
  session.pop('logged_in', None)
  return redirect(url_for('login'))


@app.route('/clear')
def clear_data():
  if not session.get('logged_in'):
    return redirect(url_for('login'))

  temp_file = os.path.join(UPLOAD_FOLDER, 'uploaded_temp.xlsx')
  if os.path.exists(temp_file):
    try:
      os.remove(temp_file)
    except Exception:
      pass

  if os.path.exists(CUSTOM_POINTS_FILE):
    try:
      os.remove(CUSTOM_POINTS_FILE)
    except Exception:
      pass

  return redirect(url_for('index'))


@app.route('/', methods=['GET', 'POST'])
def index():
  if not session.get('logged_in'):
    return redirect(url_for('login'))

  message = ''
  temp_file = os.path.join(UPLOAD_FOLDER, 'uploaded_temp.xlsx')
  search_target = None
  selected_shape_project = request.args.get('shape_proj', 'ALL')

  if request.method == 'POST':
    action = request.form.get('action')
    project_name = request.form.get('project_name', 'مشروع عام').strip()

    if action == 'search_map_url':
      maps_url = request.form.get('maps_url', '').strip()
      maps_note = (
          request.form.get('maps_note', 'موقع من رابط خرائط').strip()
          or 'موقع من رابط خرائط'
      )
      lat, lon = None, None

      if 'http' in maps_url or 'maps' in maps_url or 'goo.gl' in maps_url:
        lat, lon = get_real_coordinates_from_url(maps_url)

      if lat and lon:
        save_custom_point(lat, lon, maps_note, maps_url, project_name)
        search_target = {
            'lat': lat,
            'lon': lon,
            'note': maps_note,
            'url': maps_url,
        }
        message = f'تم حفظ النقطة في مشروع ({project_name}) بنجاح!'
      else:
        message = 'تعذر استخراج الإحداثيات من الرابط!'

    elif action == 'preview_map_url':
      maps_url = request.form.get('maps_url', '').strip()
      maps_note = (
          request.form.get('maps_note', 'موقع استعراض مؤقت').strip()
          or 'موقع استعراض مؤقت'
      )
      lat, lon = None, None

      if 'http' in maps_url or 'maps' in maps_url or 'goo.gl' in maps_url:
        lat, lon = get_real_coordinates_from_url(maps_url)

      if lat and lon:
        search_target = {
            'lat': lat,
            'lon': lon,
            'note': maps_note,
            'url': maps_url,
        }
        message = f'استعراض الموقع مؤقتاً: ({lat}, {lon})'
      else:
        message = 'تعذر استخراج الإحداثيات للاستعراض!'

    elif action == 'upload':
      if 'excelFile' in request.files:
        file = request.files['excelFile']
        if file.filename != '':
          file.save(temp_file)
          message = 'تم رفع الملف بنجاح!'

    elif action == 'add_point':
      try:
        lat = float(request.form.get('new_lat'))
        lon = float(request.form.get('new_lon'))
        note = request.form.get('new_note', 'نقطة جديدة مضافة').strip()
        save_custom_point(lat, lon, note, '#', project_name)
        search_target = {'lat': lat, 'lon': lon, 'note': note, 'url': '#'}
        message = f'تمت إضافة النقطة لمشروع ({project_name}) بنجاح!'
      except Exception:
        message = 'خطأ في إحداثيات النقطة المضافة!'

  locations = []
  if os.path.exists(temp_file):
    locations = get_resolved_data(temp_file)

  custom_points = load_custom_points()
  for cp in custom_points:
    locations.append(cp)

  locations = enrich_locations_with_shape_data(
      locations, selected_shape_project
  )

  projects_set = sorted(
      list(set(loc.get('project', 'مشروع عام') for loc in locations))
  )
  if not projects_set:
    projects_set = ['مشروع عام']

  available_shapes = get_available_shapefiles()

  selected_shape_name = 'كل المشاريع والمناطق'
  for s in available_shapes:
    if s['id'] == selected_shape_project:
      selected_shape_name = s['name']
      break

  shape_geojson = load_shapefile_as_geojson(selected_shape_project)
  effective_project_name = selected_shape_name

  grouped_dict = collections.defaultdict(list)
  for loc in locations:
    if effective_project_name != 'كل المشاريع والمناطق':
      loc['project'] = effective_project_name

    key = (
        round(loc['lat'], 6),
        round(loc['lon'], 6),
        loc.get('project', 'مشروع عام'),
    )
    grouped_dict[key].append(loc)

  grouped_locations = []
  for (lat, lon, proj), items in grouped_dict.items():
    grouped_locations.append({
        'lat': lat,
        'lon': lon,
        'project': proj,
        'count': len(items),
        'items': items,
    })

  html_template = """<!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>نظام إدارة ومتابعة المواقع والمشاريع</title>
        <link rel="icon" href="{{ url_for('static', filename='icon.png') }}" type="image/png">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.css" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.Default.css" />
        
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        
        <style>
            body { margin: 0; padding: 0; font-family: Tahoma, sans-serif; display: flex; height: 100vh; background: #f4f7f6; overflow: hidden; }
            .sidebar { width: 440px; background: #fff; box-shadow: 2px 0 10px rgba(0,0,0,0.1); padding: 15px; box-sizing: border-box; z-index: 1000; overflow-y: auto; display: flex; flex-direction: column; }
            h2 { color: #2c3e50; font-size: 16px; margin-top: 0; margin-bottom: 10px; }
            .instructions { font-size: 11px; color: #2980b9; background: #ebf5fb; padding: 10px; border-radius: 6px; line-height: 1.5; border-right: 4px solid #2980b9; margin-bottom: 10px; }
            .form-section { background: #f9f9f9; padding: 10px; border-radius: 6px; margin-bottom: 10px; border: 1px solid #e1e1e1; }
            .form-section h3 { font-size: 13px; margin: 0 0 8px 0; color: #34495e; }
            .form-group { margin-bottom: 8px; }
            label { display: block; margin-bottom: 3px; font-weight: bold; font-size: 12px; color: #34495e; }
            input[type="file"], input[type="text"], select { width: 100%; padding: 8px; border: 1px solid #bdc3c7; border-radius: 6px; box-sizing: border-box; font-size: 12px; background: #fff; }
            button { background-color: #27ae60; color: white; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-size: 13px; width: 100%; font-weight: bold; transition: background 0.3s; margin-top: 5px; }
            button:hover { background-color: #219653; }
            .btn-group { display: flex; gap: 5px; margin-top: 5px; }
            .btn-preview { background-color: #e67e22 !important; }
            .btn-preview:hover { background-color: #d35400 !important; }
            .btn-download { background-color: #2980b9 !important; margin-top: 10px; }
            .btn-download:hover { background-color: #1f618d !important; }
            .btn-clear { background-color: #e74c3c !important; text-decoration: none; display: block; text-align: center; padding: 10px; border-radius: 6px; color: white; font-weight: bold; font-size: 13px; box-sizing: border-box; transition: background 0.3s; margin-top: 5px; }
            .btn-clear:hover { background-color: #c0392b !important; }
            .btn-logout { background-color: #7f8c8d !important; text-decoration: none; display: block; text-align: center; padding: 10px; border-radius: 6px; color: white; font-weight: bold; font-size: 13px; box-sizing: border-box; transition: background 0.3s; margin-top: 5px; }
            .btn-logout:hover { background-color: #707b7c !important; }
            .designer-credit { text-align: center; font-size: 11px; color: #7f8c8d; margin-top: 10px; font-weight: bold; }
            .alert { background: #d4edda; color: #155724; padding: 8px; border-radius: 6px; font-size: 12px; margin-bottom: 10px; border-right: 4px solid #27ae60; }
            
            #map-container { flex-grow: 1; height: 100vh; width: 100%; position: relative; display: flex; flex-direction: column; }
            #map { flex-grow: 1; width: 100%; height: 100%; min-height: 500px; }

            .map-settings-box {
                background: white;
                padding: 10px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                font-family: Tahoma, sans-serif;
                font-size: 12px;
                min-width: 180px;
                z-index: 1000;
            }
            .map-settings-box label {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 6px;
                cursor: pointer;
                font-weight: bold;
                color: #2c3e50;
            }
            .map-settings-box input[type="checkbox"] { cursor: pointer; width: 15px; height: 15px; }

            .shape-label {
                background: #f1c40f !important;
                border: 2px solid #d35400 !important;
                padding: 3px 7px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                color: #000000 !important;
                box-shadow: 0 2px 5px rgba(0,0,0,0.3);
            }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>إدارة الإحداثيات</h2>
            
            <div class="instructions">
                • تأكد من وجود عمود باسم (الحي) أو (Neighborhood) في ملف الاكسل ليظهر في التقرير.
            </div>

            {% if message %}
                <div class="alert">{{ message }}</div>
            {% endif %}

            <div class="form-section" style="border: 2px solid #2c3e50; background: #eab30815;">
                <h3 style="color: #2c3e50;">تصفية المشروع</h3>
                <div class="form-group">
                    <label>اختر المشروع:</label>
                    <select id="projectFilter" onchange="changeProjectLayer()">
                        <option value="ALL">🌐 كل المشاريع والمناطق</option>
                        {% for shape in available_shapes %}
                            <option value="{{ shape.id }}" {% if selected_shape_project == shape.id %}selected{% endif %}>{{ shape.name }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>

            <div class="form-section" style="border: 2px solid #2980b9; background: #fdfefe;">
                <h3 style="color: #2980b9;">🗺️ إدخال رابط جوجل لمشروع</h3>
                <form method="POST">
                    <div class="form-group">
                        <label>اسم المشروع / منطقة الإشراف:</label>
                        <input type="text" name="project_name" placeholder="اسم المشروع" required value="مشروع عام">
                    </div>
                    <div class="form-group">
                        <label>الصق رابط جوجل مابس هنا:</label>
                        <input type="text" name="maps_url" placeholder="مثال: https://maps.app.goo.gl/..." required>
                    </div>
                    <div class="form-group">
                        <label>ملاحظة:</label>
                        <input type="text" name="maps_note" placeholder="ملاحظة الموقع">
                    </div>
                    <div class="btn-group">
                        <button type="submit" name="action" value="search_map_url" style="background-color: #2980b9; flex: 1;">حفظ النقطة 📍</button>
                        <button type="submit" name="action" value="preview_map_url" class="btn-preview" style="flex: 1;">استعراض فقط 🔍</button>
                    </div>
                </form>
            </div>

            <div class="form-section">
                <h3>📂 رفع ملف Excel</h3>
                <form method="POST" enctype="multipart/form-data">
                    <input type="hidden" name="action" value="upload">
                    <div class="form-group">
                        <input type="file" name="excelFile" accept=".xlsx, .xls, .csv" required>
                    </div>
                    <button type="submit">استخراج وعرض المواقع</button>
                </form>
            </div>

            <div class="form-section">
                <h3>➕ إضافة يدوية (بالإحداثيات)</h3>
                <form method="POST">
                    <input type="hidden" name="action" value="add_point">
                    <div class="form-group">
                        <label>اسم المشروع:</label>
                        <input type="text" name="project_name" placeholder="اسم المشروع" required value="مشروع عام">
                    </div>
                    <div class="form-group">
                        <label>خط الطول (Lat):</label>
                        <input type="text" name="new_lat" placeholder="مثال: 24.7136" required>
                    </div>
                    <div class="form-group">
                        <label>خط العرض (Lon):</label>
                        <input type="text" name="new_lon" placeholder="مثال: 46.6753" required>
                    </div>
                    <div class="form-group">
                        <label>ملاحظة:</label>
                        <input type="text" name="new_note" placeholder="اكتب تفاصيل الموقع..." required>
                    </div>
                    <button type="submit">إضافة النقطة بالإحداثيات</button>
                </form>
            </div>

            <button type="button" id="downloadReportBtn" class="btn-download">تحميل تقرير الخريطة PDF 📄</button>

            <a href="/clear" class="btn-clear">مسح الخريطة وتفريغ البيانات 🗑️</a>
            <a href="/logout" class="btn-logout">تسجيل الخروج 🔒</a>
            
            <div class="designer-credit"> Designed By Ahmed Saif Alashry </div>
        </div>
        
        <div id="map-container">
            <div id="map"></div>
        </div>

        <script>
            var map = L.map('map').setView([24.7136, 46.6753], 12);

            var satelliteBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Tiles © Esri',
                maxZoom: 19,
                crossOrigin: true
            });

            var hybridLabels = L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Labels © Esri',
                maxZoom: 19,
                crossOrigin: true
            });

            var satelliteHybrid = L.layerGroup([satelliteBase, hybridLabels]).addTo(map);

            var streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap',
                crossOrigin: true
            });

            L.control.layers({
                "قمر صناعي مع أسماء الأحياء (Hybrid)": satelliteHybrid,
                "خريطة الشوارع العادية": streetLayer
            }).addTo(map);

            setTimeout(function() {
                map.invalidateSize();
            }, 500);

            function changeProjectLayer() {
                var selectedVal = document.getElementById('projectFilter').value;
                window.location.href = "/?shape_proj=" + encodeURIComponent(selectedVal);
            }

            var shapeGeojson = {{ shape_geojson | tojson | safe }};
            var shapeLayer = null;
            if (shapeGeojson) {
                shapeLayer = L.geoJSON(shapeGeojson, {
                    style: function (feature) {
                        return {
                            color: "#e74c3c",
                            weight: 3,
                            fillColor: "#3498db",
                            fillOpacity: 0.3
                        };
                    },
                    onEachFeature: function (feature, layer) {
                        if (feature.properties) {
                            var propText = "<div style='font-family: Tahoma;'><b>بيانات منطقة الإشراف:</b><br>";
                            for (var key in feature.properties) {
                                propText += "<b>" + key + ":</b> " + feature.properties[key] + "<br>";
                            }
                            propText += "</div>";
                            layer.bindPopup(propText);

                            var displayName = feature.properties.Round_ID || feature.properties.ROUND_ID || feature.properties.round_id || feature.properties.Name || feature.properties.NAME || feature.properties.name || feature.properties.Title || feature.properties.TITLE || feature.properties.title || feature.properties.ID || Object.values(feature.properties)[0];
                            if (displayName) {
                                layer.bindTooltip(String(displayName), {
                                    permanent: true,
                                    direction: 'center',
                                    className: 'shape-label'
                                });
                            }
                        }
                    }
                }).addTo(map);

                try {
                    map.fitBounds(shapeLayer.getBounds());
                } catch(e) {}
            }

            var groupedLocations = {{ grouped_locations | tojson | safe }};
            var searchTarget = {{ search_target | tojson | safe }};
            var bounds = [];

            var allMarkersData = [];
            var currentMarkersGroup = L.layerGroup().addTo(map);

            function createPinIcon(color, count) {
                var badgeHtml = '';
                if (count > 1) {
                    badgeHtml = `<div style="position: absolute; top: -3px; right: -5px; background: #e74c3c; color: white; border-radius: 50%; min-width: 20px; height: 20px; padding: 0 4px; font-size: 11px; font-weight: bold; display: flex; align-items: center; justify-content: center; border: 2px solid white; box-shadow: 0 2px 5px rgba(0,0,0,0.3);">${count}</div>`;
                }
                return L.divIcon({
                    className: 'custom-pin',
                    html: `<div style="position: relative; width: 36px; height: 42px; filter: drop-shadow(0px 3px 4px rgba(0,0,0,0.4));">
                             <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" width="36" height="42">
                               <path fill="${color}" d="M172.2 501.4C27 291 0 269.4 0 192 0 86 86 0 192 0s192 86 192 192c0 77.4-27 99-172.2 309.4-7.8 11.2-23.9 11.2-31.6 0z"/>
                               <circle cx="192" cy="192" r="75" fill="#ffffff" />
                               <path fill="${color}" d="M192 130a50 50 0 1 0 0 100 50 50 0 1 0 0-100z"/>
                             </svg>
                             ${badgeHtml}
                           </div>`,
                    iconSize: [36, 42],
                    iconAnchor: [18, 42],
                    popupAnchor: [0, -38]
                });
            }

            groupedLocations.forEach(function(group) {
                var primaryNote = group.items[0].note;
                var popupHtml = `<div style="text-align: right; font-family: Tahoma; min-width: 200px; max-height: 250px; overflow-y: auto;">` +
                                `<b style="color: #2980b9; font-size: 12px; display: block;">المشروع: ${group.project}</b>` +
                                `<b style="color: #2c3e50; font-size: 13px; display: block; margin-bottom: 5px; border-bottom: 1px solid #ddd; padding-bottom: 4px;">إجمالي البلاغات هنا (${group.count}):</b>`;

                group.items.forEach(function(item, idx) {
                    popupHtml += `<div style="margin-bottom: 8px; padding-bottom: 6px; ${idx < group.items.length - 1 ? 'border-bottom: 1px dashed #eee;' : ''}">` +
                                 `<span style="color: #e74c3c; font-weight: bold;">#${idx+1}</span> <b>${item.note}</b><br>` +
                                 `<span style="color: #16a085; font-size: 11px;">الحي: <b>${item.neighborhood || '-'}</b> | منطقة الإشراف: <b>${item.round_id || '-'}</b></span><br>` +
                                 (item.url !== '#' ? `<a href='${item.url}' target='_blank' style='background:#27ae60; color:white; padding:3px 8px; font-size:11px; text-decoration:none; border-radius:3px; display:inline-block; margin-top:3px; font-weight:bold;'>فتح الموقع ↗</a>` : '') +
                                 `</div>`;
                });
                popupHtml += `</div>`;

                var marker = L.marker([group.lat, group.lon], {
                    icon: createPinIcon('#2980b9', group.count)
                });

                marker.bindPopup(popupHtml);
                var tooltipText = group.count === 1 ? primaryNote : `مواقع متعددة (${group.count})`;
                marker.bindTooltip(tooltipText, { permanent: false, direction: 'top' });

                allMarkersData.push({
                    marker: marker,
                    project: group.project,
                    lat: group.lat,
                    lon: group.lon,
                    items: group.items,
                    tooltipText: tooltipText
                });

                currentMarkersGroup.addLayer(marker);
                bounds.push([group.lat, group.lon]);
            });

            document.getElementById('downloadReportBtn').addEventListener('click', function() {
                var btn = this;
                btn.innerText = "جاري تجهيز الخريطة والطبقات... ⏳";
                btn.style.opacity = "0.7";

                var wasSatellite = map.hasLayer(satelliteHybrid);
                if (wasSatellite) {
                    map.removeLayer(satelliteHybrid);
                    map.addLayer(streetLayer);
                }

                setTimeout(function() {
                    var mapElement = document.getElementById('map');

                    html2canvas(mapElement, {
                        useCORS: true,
                        allowTaint: false,
                        scale: 1.5,
                        logging: false
                    }).then(function(canvas) {
                        var mapImgUrl = canvas.toDataURL('image/png');
                        
                        if (wasSatellite) {
                            map.removeLayer(streetLayer);
                            map.addLayer(satelliteHybrid);
                        }

                        var projSelect = document.getElementById('projectFilter');
                        var selectedProjName = projSelect.options[projSelect.selectedIndex].text.replace(/[🌐]/g, '').trim();
                        
                        var now = new Date();
                        var dateStr = now.toLocaleDateString('en-GB');
                        var timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
                        var dateTimeFullStr = dateStr + ' - ' + timeStr;

                        var fileDateStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
                        var fileTimeStr = String(now.getHours()).padStart(2, '0') + '-' + String(now.getMinutes()).padStart(2, '0');
                        var fileName = `تقرير_${selectedProjName}_${fileDateStr}_${fileTimeStr}.pdf`;

                        var allFlatItems = [];
                        allMarkersData.forEach(function(data) {
                            data.items.forEach(function(item) {
                                allFlatItems.push({
                                    lat: data.lat,
                                    lon: data.lon,
                                    round_id: item.round_id || '-',
                                    note: item.note,
                                    url: item.url,
                                    neighborhood: item.neighborhood || '-'
                                });
                            });
                        });

                        allFlatItems.sort(function(a, b) {
                            var rA = String(a.round_id).toLowerCase();
                            var rB = String(b.round_id).toLowerCase();
                            if (rA < rB) return -1;
                            if (rA > rB) return 1;
                            return 0;
                        });

                        var htmlContent = `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>تقرير الخريطة والبلاغات</title><style>
                            body { font-family: Tahoma, sans-serif; padding: 15px; background: #fff; color: #333; }
                            h1 { text-align: center; color: #2c3e50; font-size: 17px; margin-bottom: 5px; }
                            .report-meta { text-align: center; color: #7f8c8d; font-size: 12px; margin-bottom: 15px; direction: ltr; unicode-bidi: embed; }
                            .map-img { width: 100%; max-height: 380px; object-fit: contain; border: 1px solid #ccc; border-radius: 6px; margin-bottom: 15px; }
                            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
                            th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: right; font-size: 11px; }
                            th { background-color: #2c3e50; color: white; }
                            tr:nth-child(even) { background-color: #f9f9f9; }
                        </style></head><body>
                        <h1>تقرير خريطة وبلاغات المشروع: <span dir="ltr" style="unicode-bidi: embed;">${selectedProjName}</span></h1>
                        <div class="report-meta">${dateTimeFullStr}</div>
                        <img src="${mapImgUrl}" class="map-img">
                        <h2>تفاصيل البلاغات والمواقع </h2>
                        <table>
                            <thead><tr><th>م</th><th>المشروع</th><th>الحي</th><th>منطقة الإشراف</th><th>ملاحظة</th><th>رابط الموقع</th><th>الإحداثيات</th></tr></thead><tbody>`;

                        var counter = 1;
                        allFlatItems.forEach(function(item) {
                            htmlContent += `<tr>
                                <td>${counter++}</td>
                                <td><b>${selectedProjName}</b></td>
                                <td><span style="color: #c0392b; font-weight: bold;">${item.neighborhood}</span></td>
                                <td><span style="color: #2980b9; font-weight: bold;">${item.round_id}</span></td>
                                <td>${item.note}</td>
                                <td>${item.url !== '#' ? '<a href="' + item.url + '" target="_blank">فتح ↗</a>' : '-'}</td>
                                <td>${item.lat.toFixed(4)}, ${item.lon.toFixed(4)}</td>
                            </tr>`;
                        });

                        htmlContent += `</tbody></table></body></html>`;

                        var element = document.createElement('div');
                        element.innerHTML = htmlContent;

                        var opt = {
                            margin:       5,
                            filename:     fileName,
                            image:        { type: 'jpeg', quality: 0.90 },
                            html2canvas:  { scale: 1.5, useCORS: true, logging: false },
                            jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
                        };

                        html2pdf().from(element).set(opt).save().then(function() {
                            btn.innerText = "تحميل تقرير الخريطة PDF 📄";
                            btn.style.opacity = "1";
                        });
                    }).catch(function(err) {
                        if (wasSatellite) {
                            map.removeLayer(streetLayer);
                            map.addLayer(satelliteHybrid);
                        }
                        alert('حدث خطأ أثناء أخذ لقطة الشاشة للخريطة.');
                        btn.innerText = "تحميل تقرير الخريطة PDF 📄";
                        btn.style.opacity = "1";
                    });
                }, 1500);
            });

            var SettingsControl = L.Control.extend({
                options: { position: 'topright' },
                onAdd: function (map) {
                    var container = L.DomUtil.create('div', 'map-settings-box');
                    container.innerHTML = `<label><input type="checkbox" id="chkNotes"> إظهار الملاحظات</label>`;
                    L.DomEvent.disableClickPropagation(container);
                    setTimeout(function() {
                        document.getElementById('chkNotes').addEventListener('change', function(e) {
                            var show = e.target.checked;
                            allMarkersData.forEach(function(item) {
                                if (show) { item.marker.bindTooltip(item.tooltipText, { permanent: true, direction: 'top' }).openTooltip(); }
                                else { item.marker.unbindTooltip(); item.marker.bindTooltip(item.tooltipText, { permanent: false, direction: 'top' }); }
                            });
                        });
                    }, 100);
                    return container;
                }
            });
            map.addControl(new SettingsControl());

            if (searchTarget) {
                map.setView([searchTarget.lat, searchTarget.lon], 17);
                L.marker([searchTarget.lat, searchTarget.lon], { icon: createPinIcon('#e74c3c', 1) }).addTo(map).bindPopup(searchTarget.note).openPopup();
            } else if (shapeLayer) {
                try {
                    map.fitBounds(shapeLayer.getBounds());
                } catch(e) {}
            } else if (bounds.length > 0) {
                map.fitBounds(bounds);
            }
        </script>
    </body>
    </html>
    """
  return render_template_string(
      html_template,
      grouped_locations=grouped_locations,
      projects_set=projects_set,
      available_shapes=available_shapes,
      shape_geojson=shape_geojson,
      selected_shape_project=selected_shape_project,
      selected_shape_name=selected_shape_name,
      message=message,
      search_target=search_target,
  )


import os

if __name__ == '__main__':
  port = int(os.environ.get('PORT', 5000))
  app.run(host='0.0.0.0', port=port, debug=False)