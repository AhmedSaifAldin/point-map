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
        short_url, headers=headers, allow_redirects=True, timeout=5
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
          if 'extra_details' not in p:
            p['extra_details'] = {}
        return points
    except Exception:
      return []
  return []


def save_custom_point(
    lat, lon, note, url='#', project=' ', neighborhood='-', extra_details=None
):
  if extra_details is None:
    extra_details = {}
  points = load_custom_points()
  points.append({
      'lat': lat,
      'lon': lon,
      'note': note,
      'url': url,
      'project': project,
      'neighborhood': neighborhood,
      'extra_details': extra_details,
  })

  try:
    with open(CUSTOM_POINTS_FILE, 'w', encoding='utf-8') as f:
      json.dump(points, f, ensure_ascii=False)
  except Exception:
    pass


def save_custom_points_bulk(new_points):
  points = load_custom_points()
  points.extend(new_points)

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

          if display_name not in seen_names:
            seen_names.add(display_name)
            shapefiles_list.append({
                'id': rel_path.replace('\\', '/'),
                'name': display_name,
            })
  return shapefiles_list


def load_shapefile_as_geojson(proj_id):
  shapes_dir = os.path.join(UPLOAD_FOLDER, 'shapes')
  features_list = []

  if not proj_id or proj_id == 'ALL':
    if os.path.exists(shapes_dir):
      for root, dirs, files in os.walk(shapes_dir):
        for file in files:
          if file.endswith('.shp'):
            try:
              gdf = gpd.read_file(os.path.join(root, file))
              if gdf.crs != 'EPSG:4326':
                gdf = gdf.to_crs(epsg=4326)

              folder_name = os.path.basename(root)
              if folder_name and folder_name != 'shapes':
                proj_display = folder_name
              else:
                proj_display = os.path.splitext(file)[0].replace('_', ' ').title()

              for _, row in gdf.iterrows():
                geom_json = row['geometry'].__geo_interface__
                props = row.drop('geometry').to_dict()
                props = {
                    str(k): (
                        str(v)
                        if pd.notna(v)
                        else ''
                    )
                    for k, v in props.items()
                }
                props['parent_project_name'] = proj_display
                features_list.append({
                    'type': 'Feature',
                    'geometry': geom_json,
                    'properties': props,
                })
            except Exception:
              pass
    if features_list:
      return {'type': 'FeatureCollection', 'features': features_list}
    return None

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

      folder_name = os.path.basename(os.path.dirname(shp_path))
      if folder_name and folder_name != 'shapes':
        proj_display = folder_name
      else:
        proj_display = os.path.splitext(os.path.basename(shp_path))[0].replace('_', ' ').title()

      for _, row in gdf.iterrows():
        geom_json = row['geometry'].__geo_interface__
        props = row.drop('geometry').to_dict()
        props = {
            str(k): (
                str(v)
                if pd.notna(v)
                else ''
            )
            for k, v in props.items()
        }
        props['parent_project_name'] = proj_display
        features_list.append({
            'type': 'Feature',
            'geometry': geom_json,
            'properties': props,
        })
      return {'type': 'FeatureCollection', 'features': features_list}
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
        folder_name = os.path.basename(os.path.dirname(shp_path))
        proj_display = folder_name if (folder_name and folder_name != 'shapes') else os.path.splitext(os.path.basename(shp_path))[0].replace('_', ' ').title()
        gdfs.append((gdf, proj_display))
      except Exception:
        pass
  else:
    if os.path.exists(shapes_dir):
      for root, dirs, files in os.walk(shapes_dir):
        for file in files:
          if file.endswith('.shp'):
            try:
              full_shp_path = os.path.join(root, file)
              gdf = gpd.read_file(full_shp_path)
              if gdf.crs != 'EPSG:4326':
                gdf = gdf.to_crs(epsg=4326)
              folder_name = os.path.basename(root)
              proj_display = folder_name if (folder_name and folder_name != 'shapes') else os.path.splitext(file)[0].replace('_', ' ').title()
              gdfs.append((gdf, proj_display))
            except Exception:
              pass

  for loc in locations:
    lat = loc.get('lat')
    lon = loc.get('lon')
    round_id_val = '-'
    matched_project = None

    if lat and lon:
      pt = Point(lon, lat)
      for gdf, proj_name in gdfs:
        matched = gdf[gdf.contains(pt)]
        if not matched.empty:
          matched_project = proj_name
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
          if matched_project:
            break

    loc['round_id'] = round_id_val
    if matched_project:
      loc['project'] = matched_project
    elif not loc.get('project') or loc.get('project') == ' ':
      loc['project'] = ' '

    if 'neighborhood' not in loc:
      loc['neighborhood'] = '-'
      
  return locations


def process_excel_file(file_path):
  try:
    df = pd.read_excel(file_path)
  except Exception:
    try:
      df = pd.read_csv(file_path)
    except Exception:
      return

  if df.empty or len(df.columns) == 0:
    return

  lat_col, lon_col, url_col, note_col, project_col = None, None, None, None, None

  for col in df.columns:
    c = str(col).strip().lower()
    if any(k in c for k in ['lat', 'latitude', 'خط العرض', 'خط_العرض', 'العرض', 'y', 'lat.']):
      if not any(x in c for x in ['long', 'lon', 'الطول', 'خط الطول']):
        lat_col = col
    elif any(k in c for k in ['lon', 'long', 'longitude', 'خط الطول', 'خط_الطول', 'الطول', 'x', 'lon.', 'long.', 'location', 'loc']):
      lon_col = col
    elif any(k in c for k in ['url', 'link', 'رابط', 'maps', 'map', 'google', 'map_url', 'loc', 'location']):
      if not url_col:
        url_col = col
    elif any(k in c for k in ['ملاحظات', 'note', 'notes', 'تفاصيل', 'ملاحظة', 'description', 'name', 'title']):
      if not note_col:
        note_col = col
    elif any(k in c for k in ['مشروع', 'project', 'المشروع', 'project_name']):
      project_col = col

  if lat_col is None or lon_col is None:
    for col in df.columns:
      c = str(col).strip().lower()
      if lat_col is None and ('y' == c or 'lat' in c or 'عرض' in c):
        lat_col = col
      if lon_col is None and ('x' == c or 'lon' in c or 'long' in c or 'طول' in c):
        lon_col = col

  bulk_points = []
  
  for index, row in df.iterrows():
    lat, lon, maps_url = None, None, ''
    note = f'نقطة كشف #{index + 1}'
    project_name = ' '
    extra_details = {}

    if lat_col is not None and pd.notna(row[lat_col]):
      try:
        lat = float(str(row[lat_col]).strip())
      except Exception:
        pass
        
    if lon_col is not None and pd.notna(row[lon_col]):
      try:
        lon = float(str(row[lon_col]).strip())
      except Exception:
        pass

    if (lat is None or lon is None) and url_col is not None and pd.notna(row[url_col]):
      maps_url = str(row[url_col]).strip()
      if 'http' in maps_url or 'maps' in maps_url or 'goo.gl' in maps_url:
        lat, lon = get_real_coordinates_from_url(maps_url)

    if note_col is not None and pd.notna(row[note_col]):
      val = row[note_col]
      if str(val).strip() != '':
        note = str(val).strip()

    if project_col is not None and pd.notna(row[project_col]):
      val = row[project_col]
      if str(val).strip() != '':
        project_name = str(val).strip()

    for col in df.columns:
      if col not in [lat_col, lon_col, url_col, note_col, project_col]:
        val = row[col]
        if pd.notna(val) and str(val).strip() != '':
          extra_details[str(col)] = str(val).strip()

    if lat and lon:
      if 34 <= lat <= 55 and 16 <= lon <= 32:
        lat, lon = lon, lat

      bulk_points.append({
          'lat': lat,
          'lon': lon,
          'note': note,
          'url': maps_url if maps_url else '#',
          'project': project_name,
          'neighborhood': '-',
          'extra_details': extra_details,
      })

  if bulk_points:
    save_custom_points_bulk(bulk_points)


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
        <title>تسجيل الدخول - نظام إدارة الإحداثيات  </title>
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
  search_target = None
  selected_shape_project = request.args.get('shape_proj', 'ALL')

  if request.method == 'POST':
    action = request.form.get('action')
    project_name = (
        request.form.get('project_name', ' ').strip() or ' '
    )

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
        message = 'تم حفظ النقطة وتحديد المشروع التابع لها بنجاح!'
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

    elif action == 'search_coords_save':
      try:
        lat = float(request.form.get('coord_lat'))
        lon = float(request.form.get('coord_lon'))
        note = request.form.get('coord_note', 'نقطة إحداثيات مضافة').strip()
        save_custom_point(lat, lon, note, '#', project_name)
        search_target = {'lat': lat, 'lon': lon, 'note': note, 'url': '#'}
        message = 'تم حفظ الإحداثيات وتحديد المشروع التابع لها بنجاح!'
      except Exception:
        message = 'خطأ في إحداثيات النقطة المضافة!'

    elif action == 'search_coords_preview':
      try:
        lat = float(request.form.get('coord_lat'))
        lon = float(request.form.get('coord_lon'))
        note = request.form.get('coord_note', 'استعراض ').strip()
        search_target = {'lat': lat, 'lon': lon, 'note': note, 'url': '#'}
        message = f'استعراض الإحداثيات مؤقتاً: ({lat}, {lon})'
      except Exception:
        message = 'خطأ في إحداثيات الاستعراض!'

    elif action in ['upload_links', 'upload_coords']:
      if 'excelFile' in request.files:
        file = request.files['excelFile']
        if file.filename != '':
          path = os.path.join(UPLOAD_FOLDER, 'temp_excel.xlsx')
          file.save(path)
          process_excel_file(path)
          message = 'تمت إضافة ملف الكشف بنجاح واستخراج المواقع!'

  locations = load_custom_points()
  locations = enrich_locations_with_shape_data(
      locations, selected_shape_project
  )

  available_shapes = get_available_shapefiles()

  selected_shape_name = 'كل المشاريع والمناطق'
  for s in available_shapes:
    if s['id'] == selected_shape_project:
      selected_shape_name = s['name']
      break

  shape_geojson = load_shapefile_as_geojson(selected_shape_project)

  grouped_dict = collections.defaultdict(list)
  for loc in locations:
    key = (
        round(loc['lat'], 6),
        round(loc['lon'], 6),
        loc.get('project', ' '),
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
        <meta http-equiv="Content-Security-Policy" content="default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;">
        <title>نظام إدارة الإحداثيات  </title>
        <link rel="icon" href="{{ url_for('static', filename='icon.png') }}" type="image/png">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.css" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.Default.css" />
        
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://unpkg.com/leaflet.markercluster@1.4.1/dist/leaflet.markercluster.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        
        <style>
            html, body { margin: 0; padding: 0; font-family: Tahoma, sans-serif; height: 100vh; width: 100vw; overflow: hidden; display: flex; background: #f4f7f6; }
            
            .sidebar { width: 440px; height: 100vh; background: #fff; box-shadow: 2px 0 10px rgba(0,0,0,0.1); padding: 15px; box-sizing: border-box; z-index: 1000; display: flex; flex-direction: column; justify-content: space-between; overflow-y: auto; }
            
            h2 { color: #2c3e50; font-size: 18px; margin: 0 0 12px 0; text-align: center; }
            
            .card-section { background: #fdfdfd; border-radius: 8px; margin-bottom: 12px; border: 1px solid #dcdde1; box-shadow: 0 2px 5px rgba(0,0,0,0.03); overflow: hidden; }
            .card-header-static { padding: 10px 12px; background: #f1f2f6; display: flex; justify-content: space-between; align-items: center; font-weight: bold; font-size: 13px; color: #34495e; border-bottom: 1px solid #dcdde1; }
            .card-body-open { padding: 12px; background: #fff; }

            .form-group { margin-bottom: 10px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 12px; color: #34495e; }
            input[type="text"], select, input[type="file"] { width: 100%; padding: 8px 10px; border: 1px solid #bdc3c7; border-radius: 6px; box-sizing: border-box; font-size: 13px; background: #fff; font-family: Tahoma, sans-serif; direction: rtl; }
            select { appearance: none; -webkit-appearance: none; -moz-appearance: none; background-image: url('data:image/svg+xml;utf8,<svg fill="%2334495e" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/></svg>'); background-repeat: no-repeat; background-position: left 8px center; background-size: 16px; padding-left: 30px; }
            
            .drop-zone {
                border: 2px dashed #e67e22;
                border-radius: 6px;
                padding: 15px;
                text-align: center;
                background: #fdf8f4;
                cursor: pointer;
                transition: background 0.3s, border-color 0.3s;
                margin-bottom: 8px;
            }
            .drop-zone.dragover {
                background: #fae5d3;
                border-color: #d35400;
            }
            .drop-zone p {
                margin: 0;
                font-size: 12px;
                color: #d35400;
                font-weight: bold;
            }
            
            button { background-color: #27ae60; color: white; border: none; padding: 10px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; width: 100%; font-weight: bold; transition: background 0.3s; margin-top: 5px; }
            button:hover { background-color: #219653; }
            .btn-group { display: flex; gap: 8px; margin-top: 5px; }
            .btn-preview { background-color: #e67e22 !important; }
            .btn-preview:hover { background-color: #d35400 !important; }
            .btn-download { background-color: #2980b9 !important; padding: 10px; font-size: 13px; margin-top: 10px; }
            .btn-download:hover { background-color: #1f618d !important; }
            
            .actions-bar { display: flex; gap: 8px; margin-top: 8px; }
            .btn-clear { background-color: #e74c3c !important; text-decoration: none; display: block; text-align: center; padding: 10px; border-radius: 6px; color: white; font-weight: bold; font-size: 13px; box-sizing: border-box; flex: 1; transition: background 0.3s; }
            .btn-clear:hover { background-color: #c0392b !important; }
            .btn-logout { background-color: #7f8c8d !important; text-decoration: none; display: block; text-align: center; padding: 10px; border-radius: 6px; color: white; font-weight: bold; font-size: 13px; box-sizing: border-box; flex: 1; transition: background 0.3s; }
            .btn-logout:hover { background-color: #707b7c !important; }
            
            .designer-credit { text-align: center; font-size: 11px; color: #7f8c8d; margin-top: 10px; font-weight: bold; }
            .alert { background: #d4edda; color: #155724; padding: 8px 10px; border-radius: 6px; font-size: 12px; margin-bottom: 10px; border-right: 4px solid #27ae60; }
            
            #map-container { flex-grow: 1; height: 100vh; width: calc(100vw - 440px); position: relative; display: flex; flex-direction: column; }
            #map { flex-grow: 1; width: 100%; height: 100%; }

            .map-settings-box {
                background: white;
                padding: 10px;
                border-radius: 6px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                font-family: Tahoma, sans-serif;
                font-size: 12px;
                min-width: 200px;
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
            .map-settings-box input[type="checkbox"] { cursor: pointer; width: 14px; height: 14px; }

            /* تصميم ألوان الطبقات داخل القائمة الجانبية */
            .projects-color-body {
                max-height: 200px;
                overflow-y: auto;
            }
            .project-color-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 6px;
                gap: 10px;
            }
            .project-color-row span {
                font-weight: bold;
                color: #34495e;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                max-width: 240px;
                font-size: 12px;
            }
            .project-color-row input[type="color"] {
                border: none;
                width: 32px;
                height: 24px;
                cursor: pointer;
                background: none;
                padding: 0;
            }

            /* شريط التنقل بين النقاط بالأسهم */
            .point-navigator {
                display: flex;
                align-items: center;
                justify-content: space-between;
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 12px;
                margin-top: 5px;
            }
            .point-navigator button {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 6px 14px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                font-weight: bold;
                width: auto;
                margin-top: 0;
                transition: background 0.3s;
            }
            .point-navigator button:hover {
                background-color: #2980b9;
            }
            .point-counter-text {
                font-size: 13px;
                font-weight: bold;
                color: #2c3e50;
            }

            /* تأثير النبض المضيء للنقطة الحالية */
            @keyframes pulse-ring {
                0% { transform: scale(0.8); opacity: 1; }
                50% { transform: scale(1.6); opacity: 0.4; }
                100% { transform: scale(2.2); opacity: 0; }
            }
            .pulse-effect::after {
                content: '';
                position: absolute;
                top: -6px; right: -6px; bottom: -6px; left: -6px;
                border-radius: 50%;
                border: 3px solid #e74c3c;
                animation: pulse-ring 1.5s infinite;
                z-index: -1;
            }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div>
                <h2>إدارة الإحداثيات </h2>

                {% if message %}
                    <div class="alert">{{ message }}</div>
                {% endif %}

                <!-- تصفية المشروع -->
                <div class="card-section" style="border: 1px solid #2c3e50;">
                    <div class="card-header-static" style="color: #2c3e50; background: #eab30815;">تصفية المشروع</div>
                    <div class="card-body-open">
                        <div class="form-group" style="margin-bottom:0;">
                            <label>اختر المشروع:</label>
                            <select id="projectFilter" onchange="changeProjectLayer()">
                                <option value="ALL">🌐 كل المشاريع والمناطق</option>
                                {% for shape in available_shapes %}
                                    <option value="{{ shape.id }}" {% if selected_shape_project == shape.id %}selected{% endif %}>{{ shape.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                </div>

                <!-- ألوان الطبقات داخل القائمة الجانبية -->
                <div class="card-section" style="border: 1px solid #3498db;">
                    <div class="card-header-static" style="color: #3498db; background: #3498db15;">🎨 ألوان الطبقات (Layers Colors)</div>
                    <div class="card-body-open projects-color-body" id="projectsColorContainer">
                        <!-- يتم تعبئتها تلقائياً عبر سكربت الجافاسكريبت -->
                    </div>
                </div>

                <!-- شريط التنقل بين المواقع والنقاط بالأسهم -->
                <div class="card-section" style="border: 1px solid #8e44ad;">
                    <div class="card-header-static" style="color: #8e44ad; background: #8e44ad15;">📍 التنقل السريع بين النقاط</div>
                    <div class="card-body-open">
                        <div class="point-navigator">
    <button type="button" id="prevPointBtn" title="النقطة السابقة">▶</button>
    <span id="pointCounterDisplay" class="point-counter-text">نقطة 0 من 0</span>
    <button type="button" id="nextPointBtn" title="النقطة التالية">◀</button>
</div>
                    </div>
                </div>

                <div class="card-section" style="border: 1px solid #2980b9;">
                    <div class="card-header-static" style="color: #2980b9;">🔍 نافذة البحث (رابط / إحداثيات)</div>
                    <div class="card-body-open">
                        <form method="POST" style="margin-bottom: 12px; border-bottom: 1px solid #eee; padding-bottom: 10px;">
                            <div class="form-group">
                                <label>اسم المشروع:</label>
                                <input type="text" name="project_name" placeholder="اسم المشروع" value=" ">
                            </div>
                            <div class="form-group">
                                <label>رابط الموقع  :</label>
                                <input type="text" name="maps_url" placeholder="https://maps.app.goo.gl/..." required>
                            </div>
                            <div class="form-group">
                                <label>ملاحظة:</label>
                                <input type="text" name="maps_note" placeholder="تفاصيل الموقع...">
                            </div>
                            <div class="btn-group">
                                <button type="submit" name="action" value="search_map_url" style="background-color: #2980b9; flex: 1;">حفظ </button>
                                <button type="submit" name="action" value="preview_map_url" class="btn-preview" style="flex: 1;">استعراض </button>
                            </div>
                        </form>

                        <form method="POST">
                            <div class="form-group">
                                <label>اسم المشروع:</label>
                                <input type="text" name="project_name" placeholder="اسم المشروع" value=" ">
                            </div>
                            <div class="form-group" style="display: flex; gap: 8px;">
                                <div style="flex:1;">
                                    <label>خط الطول (Lat):</label>
                                    <input type="text" name="coord_lat" placeholder="24.7136" required>
                                </div>
                                <div style="flex:1;">
                                    <label>خط العرض (Lon):</label>
                                    <input type="text" name="coord_lon" placeholder="46.6753" required>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>ملاحظة الموقع:</label>
                                <input type="text" name="coord_note" placeholder="تفاصيل الإحداثيات..." required>
                            </div>
                            <div class="btn-group">
                                <button type="submit" name="action" value="search_coords_save" style="background-color: #2980b9; flex: 1;">حفظ  </button>
                                <button type="submit" name="action" value="search_coords_preview" class="btn-preview" style="flex: 1;">استعراض  </button>
                            </div>
                        </form>
                    </div>
                </div>

                <div class="card-section" style="border: 1px solid #e67e22;">
                    <div class="card-header-static" style="color: #e67e22;">📁 رفع ملف Excel (روابط / إحداثيات)</div>
                    <div class="card-body-open">
                        <form id="excelUploadForm" method="POST" enctype="multipart/form-data">
                            <input type="hidden" name="action" value="upload_coords">
                            
                            <div id="dropZone" class="drop-zone">
                                <p>📁 اسحب ملف Excel هنا أو اضغط للاختيار</p>
                                <input type="file" id="excelFileInput" name="excelFile" accept=".xlsx, .xls, .csv" required style="display: none;">
                            </div>
                            <div id="fileNameDisplay" style="font-size: 11px; color: #27ae60; font-weight: bold; margin-bottom: 6px; text-align: center;"></div>

                            <div style="font-size: 11px; color: rgba(231, 76, 60, 0.7); margin-bottom: 8px; text-align: center; line-height: 1.4;">
                                عند وضع خط الطول والعرض في الجدول تأكد من تسمية الأعمدة بالشكل الصحيح Latitude و Longitude أو Lat و Long
                            </div>

                            <button type="submit" style="background-color: #27ae60;"> تحميل المواقع على الخريطة  🗺️</button>
                        </form>
                    </div>
                </div>
            </div>

            <div>
                <button type="button" id="downloadReportBtn" class="btn-download">تحميل تقرير الخريطة PDF 📄</button>
                <div class="actions-bar">
                    <a href="/clear" class="btn-clear">مسح الخريطة </a>
                    <a href="/logout" class="btn-logout">تسجيل الخروج </a>
                </div>
                <div class="designer-credit"> Designed By Ahmed Saif Alashry </div>
            </div>
        </div>
        
        <div id="map-container">
            <div id="map"></div>
        </div>

        <script>
            var map = L.map('map').setView([24.7136, 46.6753], 12);

            var streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap',
                crossOrigin: true
            }).addTo(map);

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

            var satelliteHybrid = L.layerGroup([satelliteBase, hybridLabels]);

            L.control.layers({
                "خريطة الشوارع العادية (الأساسية)": streetLayer,
                "قمر صناعي مع أسماء الأحياء (Hybrid)": satelliteHybrid
            }).addTo(map);

            setTimeout(function() {
                map.invalidateSize();
            }, 500);

            var dropZone = document.getElementById('dropZone');
            var fileInput = document.getElementById('excelFileInput');
            var fileNameDisplay = document.getElementById('fileNameDisplay');
            var excelUploadForm = document.getElementById('excelUploadForm');

            dropZone.addEventListener('click', function() {
                fileInput.click();
            });

            fileInput.addEventListener('change', function(e) {
                if (fileInput.files.length > 0) {
                    fileNameDisplay.innerText = "الملف المختار: " + fileInput.files[0].name;
                }
            });

            ['dragenter', 'dragover'].forEach(eventName => {
                dropZone.addEventListener(eventName, function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    dropZone.classList.add('dragover');
                }, false);
            });

            ['dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    dropZone.classList.remove('dragover');
                }, false);
            });

            dropZone.addEventListener('drop', function(e) {
                var dt = e.dataTransfer;
                var files = dt.files;
                if (files.length > 0) {
                    fileInput.files = files;
                    fileNameDisplay.innerText = "الملف المختار: " + files[0].name;
                }
            }, false);

            function changeProjectLayer() {
                var selectedVal = document.getElementById('projectFilter').value;
                window.location.href = "/?shape_proj=" + encodeURIComponent(selectedVal);
            }

            var shapeGeojson = {{ shape_geojson | tojson | safe }};
            var availableShapes = {{ available_shapes | tojson | safe }};
            var shapeLayer = null;
            
            var shapeLabelsGroup = L.layerGroup();
            var shapeFeatureLayers = [];

            var layerCustomColors = JSON.parse(localStorage.getItem('layerCustomColors') || '{}');
            var defaultColorsList = ['#e74c3c', '#3498db', '#27ae60', '#e67e22', '#8e44ad', '#16a085', '#d35400', '#2c3e50'];
            var layerColorMap = {};

            var allProjectsList = [];
            availableShapes.forEach(function(s) {
                if (!allProjectsList.includes(s.name)) {
                    allProjectsList.push(s.name);
                }
            });

            if (shapeGeojson && shapeGeojson.features) {
                shapeGeojson.features.forEach(function(feat) {
                    var pName = feat.properties.parent_project_name || ' ';
                    if (!allProjectsList.includes(pName)) {
                        allProjectsList.push(pName);
                    }
                });
            }

            allProjectsList.forEach(function(proj, index) {
                if (layerCustomColors[proj]) {
                    layerColorMap[proj] = layerCustomColors[proj];
                } else {
                    layerColorMap[proj] = defaultColorsList[index % defaultColorsList.length];
                }
            });

            // تعبئة ألوان الطبقات داخل القائمة الجانبية تلقائياً
            var colorContainerHtml = '';
            if (allProjectsList.length === 0) {
                colorContainerHtml = `<div style="text-align: center; color: #7f8c8d; font-size: 11px;">لا توجد طبقات مشاريع متاحة</div>`;
            } else {
                allProjectsList.forEach(function(proj) {
                    var currentColor = layerColorMap[proj] || '#e74c3c';
                    colorContainerHtml += `<div class="project-color-row">` +
                                            `<span title="${proj}">${proj}</span>` +
                                            `<input type="color" class="layer-color-picker" data-project="${proj}" value="${currentColor}">` +
                                          `</div>`;
                });
            }
            document.getElementById('projectsColorContainer').innerHTML = colorContainerHtml;

            // تفعيل أحداث تغيير الألوان للطبقات
            document.querySelectorAll('.layer-color-picker').forEach(function(picker) {
                picker.addEventListener('input', function(e) {
                    var projName = e.target.getAttribute('data-project');
                    var newColor = e.target.value;
                    
                    layerColorMap[projName] = newColor;
                    layerCustomColors[projName] = newColor;
                    localStorage.setItem('layerCustomColors', JSON.stringify(layerCustomColors));

                    shapeFeatureLayers.forEach(function(item) {
                        if (item.project === projName) {
                            item.layer.setStyle({
                                color: newColor,
                                fillColor: newColor
                            });
                        }
                    });
                });
            });

            if (shapeGeojson) {
                shapeLayer = L.geoJSON(shapeGeojson, {
                    style: function (feature) {
                        var pName = feature.properties ? (feature.properties.parent_project_name || ' ') : ' ';
                        var col = layerColorMap[pName] || '#e74c3c';
                        return {
                            color: col,
                            weight: 3,
                            fillColor: col,
                            fillOpacity: 0.3
                        };
                    },
                    onEachFeature: function (feature, layer) {
                        var pName = feature.properties ? (feature.properties.parent_project_name || ' ') : ' ';
                        shapeFeatureLayers.push({
                            layer: layer,
                            project: pName
                        });

                        if (feature.properties) {
                            var parentProject = pName;
                            var roundIdName = feature.properties.Round_ID || feature.properties.ROUND_ID || feature.properties.round_id || feature.properties.Name || feature.properties.NAME || feature.properties.name || feature.properties.Title || feature.properties.TITLE || feature.properties.title || feature.properties.ID || Object.values(feature.properties)[0] || '-';

                            try {
                                var center = layer.getBounds().getCenter();
                                var textMarker = L.marker(center, {
                                    icon: L.divIcon({
                                        className: 'shape-text-label',
                                        html: `<div style="background: rgba(255, 255, 255, 0.9); padding: 2px 6px; border: 1px solid #e74c3c; border-radius: 4px; font-size: 11px; font-weight: bold; color: #c0392b; white-space: nowrap; box-shadow: 0 1px 3px rgba(0,0,0,0.2);">${roundIdName}</div>`,
                                        iconSize: [60, 20],
                                        iconAnchor: [30, 10]
                                    })
                                });
                                shapeLabelsGroup.addLayer(textMarker);
                            } catch(e) {}

                            var propText = `<div style='font-family: Tahoma; min-width: 180px;'>` +
                                           `<b style='color: #2c3e50; font-size: 13px; border-bottom: 2px solid #3498db; display: block; padding-bottom: 3px; margin-bottom: 5px;'>بيانات منطقة الإشراف</b>` +
                                           `<div style='margin-bottom: 4px; font-size: 12px;'>اسم المشروع التابع: <b>${parentProject}</b></div>` +
                                           `<div style='margin-bottom: 4px; font-size: 12px;'>منطقة الإشراف: <b style='color: #e74c3c;'>${roundIdName}</b></div>`;

                            for (var key in feature.properties) {
                                if (key !== 'parent_project_name' && key !== 'Round_ID' && key !== 'ROUND_ID' && key !== 'round_id' && key !== 'Name' && key !== 'NAME' && key !== 'name' && key !== 'Title' && key !== 'TITLE' && key !== 'title' && key !== 'ID') {
                                    propText += `<div style='font-size: 11px; color: #555;'><b>${key}:</b> ${feature.properties[key]}</div>`;
                                }
                            }
                            propText += `</div>`;
                            layer.bindPopup(propText);
                        }
                    }
                }).addTo(map);
            }

            var groupedLocations = {{ grouped_locations | tojson | safe }};
            var searchTarget = {{ search_target | tojson | safe }};
            var bounds = [];

            var allMarkersData = [];
            var currentMarkersGroup = L.markerClusterGroup().addTo(map);

            function createPinIcon(count, isHighlighted = false) {
                var badgeHtml = '';
                if (count > 1) {
                    badgeHtml = `<div style="position: absolute; top: -2px; right: -4px; background: #e74c3c; color: white; border-radius: 50%; min-width: 16px; height: 16px; padding: 0 3px; font-size: 9px; font-weight: bold; display: flex; align-items: center; justify-content: center; border: 1.5px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.3);">${count}</div>`;
                }
                var pulseClass = isHighlighted ? ' pulse-effect' : '';
                var pinColor = isHighlighted ? '#e74c3c' : '#8e44ad';

                return L.divIcon({
                    className: 'custom-pin' + pulseClass,
                    html: `<div style="position: relative; width: 24px; height: 30px; filter: drop-shadow(0px 2px 3px rgba(0,0,0,0.4));">
                             <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" width="24" height="30">
                               <path fill="${pinColor}" d="M172.2 501.4C27 291 0 269.4 0 192 0 86 86 0 192 0s192 86 192 192c0 77.4-27 99-172.2 309.4-7.8 11.2-23.9 11.2-31.6 0z"/>
                               <circle cx="192" cy="192" r="75" fill="#ffffff" />
                               <path fill="${pinColor}" d="M192 130a50 50 0 1 0 0 100 50 50 0 1 0 0-100z"/>
                             </svg>
                             ${badgeHtml}
                           </div>`,
                    iconSize: [24, 30],
                    iconAnchor: [12, 30],
                    popupAnchor: [0, -28]
                });
            }

            groupedLocations.forEach(function(group) {
                var primaryNote = group.items[0].note;
                
                var popupHtml = `<div style="text-align: right; font-family: Tahoma; min-width: 250px; max-height: 300px; overflow-y: auto;">` +
                                `<b style="color: #2980b9; font-size: 13px; display: block; border-bottom: 2px solid #2980b9; padding-bottom: 4px; margin-bottom: 6px;">📁 المشروع: ${group.project}</b>` +
                                `<div style="font-size: 11px; color: #34495e; margin-bottom: 4px;">خط الطول (Lat): <b>${group.lat.toFixed(5)}</b></div>` +
                                `<div style="font-size: 11px; color: #34495e; margin-bottom: 8px;">خط العرض (Lon): <b>${group.lon.toFixed(5)}</b></div>`;

                group.items.forEach(function(item, idx) {
                    popupHtml += `<div style="background: #f8f9fa; padding: 6px; border-radius: 5px; margin-bottom: 6px; border: 1px solid #e1e1e1;">` +
                                 `<div style="color: #e74c3c; font-weight: bold; font-size: 11px;"> / النقطة #${idx+1}</div>` +
                                 `<div style="margin: 3px 0; color: #2c3e50;"><b>الملاحظة:</b> ${item.note}</div>` +
                                 `<div style="color: #16a085; font-size: 11px; margin-bottom: 3px;">منطقة الإشراف: <b>${item.round_id || '-'}</b></div>`;
                    
                    if (item.extra_details) {
                        for (var key in item.extra_details) {
                            if (item.extra_details.hasOwnProperty(key)) {
                                popupHtml += `<div style="font-size: 11px; color: #34495e; border-top: 1px dashed #dcdde1; padding-top: 2px; margin-top: 2px;"><b>${key}:</b> ${item.extra_details[key]}</div>`;
                            }
                        }
                    }

                    if (item.url !== '#' && item.url !== '') {
                        popupHtml += `<a href='${item.url}' target='_blank' style='background:#27ae60; color:white; padding:2px 6px; font-size:10px; text-decoration:none; border-radius:3px; display:inline-block; margin-top:4px; font-weight:bold;'>فتح رابط جوجل ↗</a>`;
                    }
                    popupHtml += `</div>`;
                });
                popupHtml += `</div>`;

                var marker = L.marker([group.lat, group.lon], {
                    icon: createPinIcon(group.count, false)
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
                    tooltipText: tooltipText,
                    count: group.count
                });

                currentMarkersGroup.addLayer(marker);
                bounds.push([group.lat, group.lon]);
            });

            // نظام التنقل بالأسهم بين النقاط مع العداد والتأثير المضيء
            var currentPointIndex = 0;
            var totalPoints = allMarkersData.length;
            var counterDisplay = document.getElementById('pointCounterDisplay');

            function updatePointNavigation(index) {
                if (totalPoints === 0) {
                    counterDisplay.innerText = "لا توجد نقاط متاحة";
                    return;
                }

                if (index < 0) currentPointIndex = totalPoints - 1;
                else if (index >= totalPoints) currentPointIndex = 0;
                else currentPointIndex = index;

                counterDisplay.innerText = `نقطة ${currentPointIndex + 1} من ${totalPoints}`;

                // إعادة تعيين أيقونات جميع النقاط للطبيعي
                allMarkersData.forEach(function(item, idx) {
                    item.marker.setIcon(createPinIcon(item.count, false));
                });

                // تفعيل تأثير النبض وزوم على النقطة الحالية
                var targetData = allMarkersData[currentPointIndex];
                targetData.marker.setIcon(createPinIcon(targetData.count, true));

                // التعامل مع التجمعات (MarkerCluster) إذا كانت النقطة داخل تجمع
                currentMarkersGroup.zoomToShowLayer(targetData.marker, function() {
                    map.setView([targetData.lat, targetData.lon], 17, { animate: true });
                    targetData.marker.openPopup();
                });
            }

            if (totalPoints > 0) {
                counterDisplay.innerText = `نقطة 1 من ${totalPoints}`;
            } else {
                counterDisplay.innerText = `نقطة 0 من 0`;
            }

            document.getElementById('prevPointBtn').addEventListener('click', function() {
                if (totalPoints > 0) updatePointNavigation(currentPointIndex - 1);
            });

            document.getElementById('nextPointBtn').addEventListener('click', function() {
                if (totalPoints > 0) updatePointNavigation(currentPointIndex + 1);
            });

            document.getElementById('downloadReportBtn').addEventListener('click', function() {
                var btn = this;
                btn.innerText = "جاري تجهيز وتصدير التقرير... ⏳";
                btn.style.opacity = "0.7";

                var mapElement = document.getElementById('map');

                html2canvas(mapElement, {
                    useCORS: true,
                    allowTaint: true,
                    scale: 1.5,
                    logging: false
                }).then(function(canvas) {
                    var mapImgUrl = canvas.toDataURL('image/png');

                    var projSelect = document.getElementById('projectFilter');
                    var selectedProjName = projSelect.options[projSelect.selectedIndex].text.replace(/[🌐]/g, '').trim();
                    
                    var now = new Date();
                    var dateStr = now.toLocaleDateString('en-GB');
                    var timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
                    var dateTimeFullStr = dateStr + ' - ' + timeStr;

                    var fileDateStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
                    var fileTimeStr = String(now.getHours()).padStart(2, '0') + '-' + String(now.getMinutes()).padStart(2, '0');
                    var fileName = `تقرير_${selectedProjName}_${fileDateStr}_${fileTimeStr}.pdf`;

                    var allDynamicKeys = [];
                    allMarkersData.forEach(function(data) {
                        data.items.forEach(function(item) {
                            if (item.extra_details) {
                                Object.keys(item.extra_details).forEach(function(k) {
                                    if (!allDynamicKeys.includes(k)) {
                                        allDynamicKeys.push(k);
                                    }
                                });
                            }
                        });
                    });

                    var allFlatItems = [];
                    allMarkersData.forEach(function(data) {
                        data.items.forEach(function(item) {
                            var mapLink = (item.url && item.url !== '#') ? item.url : `https://www.google.com/maps?q=${data.lat},${data.lon}`;
                            allFlatItems.push({
                                lat: data.lat,
                                lon: data.lon,
                                round_id: item.round_id || '-',
                                note: item.note,
                                url: mapLink,
                                project: data.project,
                                extra_details: item.extra_details || {}
                            });
                        });
                    });

                    var htmlContent = `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><title>تقرير الخريطة والبيانات</title><style>
                        body { font-family: Tahoma, sans-serif; padding: 10px; background: #fff; color: #333; }
                        h1 { text-align: center; color: #2c3e50; font-size: 15px; margin-bottom: 2px; }
                        .report-meta { text-align: center; color: #7f8c8d; font-size: 10px; margin-bottom: 8px; direction: ltr; unicode-bidi: embed; }
                        .map-container-pdf { width: 100%; text-align: center; margin-bottom: 10px; }
                        .map-img { width: 100%; max-height: 320px; object-fit: contain; border: 1px solid #ccc; border-radius: 4px; }
                        table { width: 100%; border-collapse: collapse; margin-top: 5px; }
                        th, td { border: 1px solid #ddd; padding: 5px 8px; text-align: right; font-size: 9px; }
                        th { background-color: #2c3e50; color: white; }
                        tr:nth-child(even) { background-color: #f9f9f9; }
                        .map-btn { background-color: #27ae60; color: white !important; padding: 2px 6px; text-decoration: none; border-radius: 3px; font-weight: bold; display: inline-block; font-size: 8px; }
                    </style></head><body>
                    <h1>تقرير المشروع: <span dir="ltr" style="unicode-bidi: embed;">${selectedProjName}</span></h1>
                    <div class="report-meta">${dateTimeFullStr}</div>
                    <div class="map-container-pdf"><img src="${mapImgUrl}" class="map-img"></div>
                    <h2 style="font-size: 12px; margin: 8px 0 4px 0; color: #2c3e50;">جدول تفاصيل البيانات والمواقع</h2>
                    <table>
                        <thead><tr>
                            <th>م</th>
                            <th>المشروع</th>
                            <th>ملاحظة</th>
                            <th>خط الطول (Lat)</th>
                            <th>خط العرض (Lon)</th>
                            <th>منطقة الإشراف</th>`;
                    
                    allDynamicKeys.forEach(function(key) {
                        htmlContent += `<th>${key}</th>`;
                    });

                    htmlContent += `<th>الذهاب للموقع</th></tr></thead><tbody>`;

                    var counter = 1;
                    allFlatItems.forEach(function(item) {
                        htmlContent += `<tr>
                            <td>${counter++}</td>
                            <td><b>${item.project}</b></td>
                            <td>${item.note}</td>
                            <td>${item.lat.toFixed(5)}</td>
                            <td>${item.lon.toFixed(5)}</td>
                            <td><span style="color: #2980b9; font-weight: bold;">${item.round_id}</span></td>`;
                        
                        allDynamicKeys.forEach(function(key) {
                            var val = item.extra_details[key] !== undefined ? item.extra_details[key] : '-';
                            htmlContent += `<td>${val}</td>`;
                        });

                        htmlContent += `<td><a href="${item.url}" target="_blank" class="map-btn">فتح الموقع ↗</a></td></tr>`;
                    });

                    htmlContent += `</tbody></table></body></html>`;

                    var element = document.createElement('div');
                    element.innerHTML = htmlContent;

                    var opt = {
                        margin:       5,
                        filename:     fileName,
                        image:        { type: 'jpeg', quality: 0.90 },
                        html2canvas:  { scale: 2, useCORS: true, allowTaint: true, logging: false },
                        jsPDF:        { unit: 'mm', format: 'a4', orientation: 'landscape' }
                    };

                    html2pdf().from(element).set(opt).save().then(function() {
                        btn.innerText = "تحميل تقرير الخريطة PDF 📄";
                        btn.style.opacity = "1";
                    });
                }).catch(function(err) {
                    alert('حدث خطأ أثناء أخذ لقطة الشاشة للخريطة.');
                    btn.innerText = "تحميل تقرير الخريطة PDF 📄";
                    btn.style.opacity = "1";
                });
            });

            var SettingsControl = L.Control.extend({
                options: { position: 'topright' },
                onAdd: function (map) {
                    var container = L.DomUtil.create('div', 'map-settings-box');
                    container.innerHTML = `<label><input type="checkbox" id="chkNotes"> إظهار الملاحظات</label>` +
                                          `<label><input type="checkbox" id="chkShowSupervision" checked> إظهار مناطق الإشراف</label>` +
                                          `<label><input type="checkbox" id="chkHideSupervision"> إخفاء مناطق الإشراف</label>` +
                                          `<label><input type="checkbox" id="chkShowSupNames"> إظهار أسامي مناطق الإشراف</label>`;
                    L.DomEvent.disableClickPropagation(container);
                    setTimeout(function() {
                        document.getElementById('chkNotes').addEventListener('change', function(e) {
                            var show = e.target.checked;
                            allMarkersData.forEach(function(item) {
                                if (show) { item.marker.bindTooltip(item.tooltipText, { permanent: true, direction: 'top' }).openTooltip(); }
                                else { item.marker.unbindTooltip(); item.marker.bindTooltip(item.tooltipText, { permanent: false, direction: 'top' }); }
                            });
                        });

                        var chkShowSup = document.getElementById('chkShowSupervision');
                        var chkHideSup = document.getElementById('chkHideSupervision');
                        var chkShowSupNames = document.getElementById('chkShowSupNames');

                        chkShowSup.addEventListener('change', function(e) {
                            if (e.target.checked) {
                                chkHideSup.checked = false;
                                if (shapeLayer && !map.hasLayer(shapeLayer)) map.addLayer(shapeLayer);
                                if (chkShowSupNames.checked && shapeLabelsGroup && !map.hasLayer(shapeLabelsGroup)) map.addLayer(shapeLabelsGroup);
                            } else {
                                if (!chkHideSup.checked) chkHideSup.checked = true;
                                if (shapeLayer && map.hasLayer(shapeLayer)) map.removeLayer(shapeLayer);
                                if (map.hasLayer(shapeLabelsGroup)) map.removeLayer(shapeLabelsGroup);
                            }
                        });

                        chkHideSup.addEventListener('change', function(e) {
                            if (e.target.checked) {
                                chkShowSup.checked = false;
                                if (shapeLayer && map.hasLayer(shapeLayer)) map.removeLayer(shapeLayer);
                                if (map.hasLayer(shapeLabelsGroup)) map.removeLayer(shapeLabelsGroup);
                            } else {
                                if (!chkShowSup.checked) chkShowSup.checked = true;
                                if (shapeLayer && !map.hasLayer(shapeLayer)) map.addLayer(shapeLayer);
                                if (chkShowSupNames.checked && shapeLabelsGroup && !map.hasLayer(shapeLabelsGroup)) map.addLayer(shapeLabelsGroup);
                            }
                        });

                        chkShowSupNames.addEventListener('change', function(e) {
                            var showNames = e.target.checked;
                            if (showNames) {
                                if (chkShowSup.checked && shapeLabelsGroup && !map.hasLayer(shapeLabelsGroup)) {
                                    map.addLayer(shapeLabelsGroup);
                                }
                            } else {
                                if (shapeLabelsGroup && map.hasLayer(shapeLabelsGroup)) {
                                    map.removeLayer(shapeLabelsGroup);
                                }
                            }
                        });
                    }, 100);
                    return container;
                }
            });
            map.addControl(new SettingsControl());

            if (searchTarget) {
                map.setView([searchTarget.lat, searchTarget.lon], 17);
                L.marker([searchTarget.lat, searchTarget.lon], { icon: createPinIcon(1, true) }).addTo(map).bindPopup(searchTarget.note).openPopup();
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
      available_shapes=available_shapes,
      shape_geojson=shape_geojson,
      selected_shape_project=selected_shape_project,
      selected_shape_name=selected_shape_name,
      message=message,
      search_target=search_target,
  )


if __name__ == '__main__':
  port = int(os.environ.get('PORT', 5000))
  app.run(host='0.0.0.0', port=port, debug=False)