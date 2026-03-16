import pandas as pd
import requests
from geopy.distance import geodesic
import os
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
import io

load_dotenv()  # last miljøvariabler fra .env

CLIENT_ID = "0fa358f8-1ba2-4c05-bff7-2977868375c2" 
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

def finn_naermeste_stasjon(lat, lon, stasjon_index=0):
    """
    Returnerer stasjonen på valgt index og DataFrame med alle stasjoner sortert etter avstand.
    """
    import requests
    import pandas as pd
    from geopy.distance import geodesic

    url_stations = "https://frost.met.no/sources/v0.jsonld"
    response = requests.get(url_stations, auth=(CLIENT_ID, ''))

    if response.status_code != 200:
        raise RuntimeError(f"Frost API returnerte {response.status_code}: {response.text}")

    data_json = response.json()
    if 'data' not in data_json:
        raise RuntimeError(f"Frost API-responsen mangler 'data': {data_json}")

    stations = data_json['data']
    stations_list = []
    for s in stations:
        if 'geometry' in s and 'coordinates' in s['geometry']:
            coords = (s['geometry']['coordinates'][1], s['geometry']['coordinates'][0])
            distance = geodesic((lat, lon), coords).km
            stations_list.append({'id': s['id'], 'name': s['name'], 'distance_km': distance})

    stations_df = pd.DataFrame(stations_list).sort_values('distance_km').reset_index(drop=True)

    # Velg stasjonen basert på stasjon_index
    nearest_station = stations_df.iloc[stasjon_index]['id']

    return nearest_station, stations_df

def fetch_weather(stasjon_id, start, end):
    """
    Henter observasjoner fra Frost API for gitte tidsperioder.
    """
    elements = "air_temperature,wind_speed,sum(precipitation_amount PT1H)"
    url = f"https://frost.met.no/observations/v0.jsonld?sources={stasjon_id}&elements={elements}&referencetime={start}/{end}"

    response = requests.get(url, auth=(CLIENT_ID, ''))
    if response.status_code != 200:
        print("Feil:", response.status_code)
        return pd.DataFrame()
    
    data = response.json()
    observations = data.get('data', [])
    records = []

    for obs in observations:
        row = {"timestamp": obs.get('referenceTime')}
        for element in obs.get('observations', []):
            eid = element['elementId']
            value = element.get('value')
            
            # Gjør kolonnenavn mer lesbart
            if eid == "sum(precipitation_amount PT1H)":
                eid = "precipitation_mm"
            
            row[eid] = value
        records.append(row)

    return pd.DataFrame(records)

def fetch_weather_periods_hourly(stasjon_id, periods):
    """
    Henter værdata for flere perioder og returnerer timeaggret dataframe.
    """
    dfs = []
    for start, end in periods:
        df = fetch_weather(stasjon_id, start, end)
        dfs.append(df)

    if dfs:
        weather_df = pd.concat(dfs, ignore_index=True)
        weather_df['timestamp'] = pd.to_datetime(weather_df['timestamp'])
        weather_df_hourly = weather_df[weather_df['timestamp'].dt.minute == 0].copy()
        weather_df_hourly = weather_df_hourly.sort_values('timestamp').reset_index(drop=True)
        weather_df_hourly['timestamp'] = weather_df_hourly['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        return weather_df_hourly
    else:
        return pd.DataFrame()

def upload_to_azure(df: pd.DataFrame, container_name: str, blob_name: str):
    """
    Laster opp en dataframe som CSV til Azure Blob Storage.
    """
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    blob_client.upload_blob(csv_buffer.getvalue(), overwrite=True)
    print(f"CSV lagret i Azure Blob Storage: {container_name}/{blob_name}")