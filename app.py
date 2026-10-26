import collections
import json
import os
import re
import tempfile
import uuid
from flask import (
    Flask,
    redirect,
    render_template,
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
app.config['TEMPLATES_AUTO_RELOAD'] = True

USERNAME = 'admin'
PASSWORD = '123'


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
        short_url, headers=headers, allow_redirects=True, timeout=3
    )
    final_url = response.url

    match_final = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
    if match_final:
      return float(match_final.group(1)), float(match_final.group(2))

    match_q_final = re.search(r'q=(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
    if match_q_final:
      return float(match_q_final.group(1)), float(match_q_final.group(2))

  except Exception:
    pass

  return None, None


def get_user_files():
  token = session.get('user_token', 'default_guest')
  points_file = os.path.join(UPLOAD_FOLDER, f'custom_points_{token}.json')
  chunks_file = os.path.join(UPLOAD_FOLDER, f'chunks_{token}.json')
  return points_file, chunks_file


def load_custom_points():
  points_file, _ = get_user_files()
  if os.path.exists(points_file):
    try:
      with open(points_file, 'r', encoding='utf-8') as f:
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
  points_file, _ = get_user_files()
  try:
    with open(points_file, 'w', encoding='utf-8') as f:
      json.dump(points, f, ensure_ascii=False)
  except Exception:
    pass


def save_custom_points_bulk(new_points):
  points = load_custom_points()
  points.extend(new_points)
  points_file, _ = get_user_files()
  try:
    with open(points_file, 'w', encoding='utf-8') as f:
      json.dump(points, f, ensure_ascii=False)
  except Exception:
    pass


def load_chunks():
  _, chunks_file = get_user_files()
  if os.path.exists(chunks_file):
    try:
      with open(chunks_file, 'r', encoding='utf-8') as f:
        return json.load(f)
    except Exception:
      return []
  return []


def save_chunks(chunks):
  _, chunks_file = get_user_files()
  try:
    with open(chunks_file, 'w', encoding='utf-8') as f:
      json.dump(chunks, f, ensure_ascii=False)
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
            except Exception as e:
              print(f'Error reading shp: {e}')
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
      print('Error loading specific shapefile:', e)
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
        try:
          possible_matches_index = list(gdf.sindex.intersection(pt.bounds))
          if possible_matches_index:
            possible_matches = gdf.iloc[possible_matches_index]
            matched = possible_matches[possible_matches.contains(pt)]
            if not matched.empty:
              matched_project = proj_name
              props = matched.iloc[0]
              for col in props.index:
                if any(k in col.lower() for k in ['round_id', 'roundid', 'round']):
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
        except Exception:
          pass

    loc['round_id'] = round_id_val
    if matched_project:
      loc['project'] = matched_project
    elif not loc.get('project') or loc.get('project') == ' ':
      loc['project'] = ' '

    if 'neighborhood' not in loc:
      loc['neighborhood'] = '-'

  return locations


def process_excel_file_to_chunks(file_path, chunk_size=200):
  try:
    df = pd.read_excel(file_path)
  except Exception:
    try:
      df = pd.read_csv(file_path)
    except Exception:
      return 0

  if df.empty or len(df.columns) == 0:
    return 0

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

    if url_col is not None and pd.notna(row[url_col]):
      maps_url = str(row[url_col]).strip()

    if (lat is None or lon is None) and maps_url:
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

  if not bulk_points:
    return 0

  existing_chunks = load_chunks()
  new_chunks = []

  for i in range(0, len(bulk_points), chunk_size):
    chunk_pts = bulk_points[i:i + chunk_size]
    chunk_id = str(uuid.uuid4())[:8]
    chunk_name = f"مجموعة ملف ({i + 1} إلى {min(i + chunk_size, len(bulk_points))}) - {len(chunk_pts)} نقطة"
    new_chunks.append({
        'id': chunk_id,
        'name': chunk_name,
        'points': chunk_pts,
        'added': False
    })

  existing_chunks.extend(new_chunks)
  save_chunks(existing_chunks)
  return len(new_chunks)


@app.route('/login', methods=['GET', 'POST'])
def login():
  error = ''
  if request.method == 'POST':
    if (
        request.form['username'] == USERNAME
        and request.form['password'] == PASSWORD
    ):
      session['logged_in'] = True
      if 'user_token' not in session:
        session['user_token'] = str(uuid.uuid4())
      return redirect(url_for('index'))
    else:
      error = 'اسم المستخدم أو كلمة المرور غير صحيحة!'

  login_template = """<!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>تسجيل الدخول - نظام إدارة الإحداثيات</title>
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
  session.pop('user_token', None)
  return redirect(url_for('login'))


@app.route('/clear')
def clear_data():
  if not session.get('logged_in'):
    return redirect(url_for('login'))

  points_file, chunks_file = get_user_files()
  for f_path in [points_file, chunks_file]:
    if os.path.exists(f_path):
      try:
        os.remove(f_path)
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
          try:
            chunk_size_val = int(request.form.get('chunk_size', 200))
            if chunk_size_val < 1:
              chunk_size_val = 200

            temp_dir = tempfile.gettempdir()
            path = os.path.join(temp_dir, f'temp_excel_{uuid.uuid4().hex}.xlsx')
            file.save(path)
            try:
              num_chunks = process_excel_file_to_chunks(
                  path, chunk_size=chunk_size_val
              )
            finally:
              if os.path.exists(path):
                os.remove(path)
            if num_chunks > 0:
              message = f'تمت معالجة الملف وتقسيمه إلى {num_chunks} مجموعات (بحجم {chunk_size_val} نقطة لكل مجموعة) بنجاح!'
            else:
              message = 'تعذر استخراج بيانات صحيحة من الملف!'
          except Exception as e:
            message = f'حدث خطأ أثناء معالجة الملف: {str(e)}'

    elif action == 'add_chunk_to_map':
      chunk_id = request.form.get('chunk_id')
      chunks = load_chunks()
      target_chunk = None
      for ch in chunks:
        if ch['id'] == chunk_id and not ch['added']:
          target_chunk = ch
          break
      if target_chunk:
        save_custom_points_bulk(target_chunk['points'])
        target_chunk['added'] = True
        save_chunks(chunks)
        message = f'تمت إضافة "{target_chunk["name"]}" إلى الخريطة بنجاح!'

    elif action == 'add_all_chunks':
      chunks = load_chunks()
      added_count = 0
      for ch in chunks:
        if not ch['added']:
          save_custom_points_bulk(ch['points'])
          ch['added'] = True
          added_count += 1
      if added_count > 0:
        save_chunks(chunks)
        message = f'تمت إضافة جميع المجموعات ({added_count}) إلى الخريطة بنجاح!'

    elif action == 'clear_chunks':
      _, chunks_file = get_user_files()
      if os.path.exists(chunks_file):
        try:
          os.remove(chunks_file)
        except Exception:
          pass
      message = 'تم مسح المجموعات المعالجة بنجاح.'

  locations = load_custom_points()
  locations = enrich_locations_with_shape_data(
      locations, selected_shape_project
  )

  chunks_list = load_chunks()
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

  return render_template(
      'index.html',
      grouped_locations=grouped_locations,
      available_shapes=available_shapes,
      shape_geojson=shape_geojson,
      selected_shape_project=selected_shape_project,
      selected_shape_name=selected_shape_name,
      message=message,
      search_target=search_target,
      chunks_list=chunks_list,
  )


if __name__ == '__main__':
  port = int(os.environ.get('PORT', 80))
  app.run(host='0.0.0.0', port=port, debug=False)