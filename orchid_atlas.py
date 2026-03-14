import pandas as pd
import pydeck as pdk

df = pd.read_csv("orchid_points.csv")

df = df.rename(columns={"decimal_latitude": "lat", "decimal_longitude": "lon"})

df = df.dropna(subset=["lat", "lon"])

layer = pdk.Layer("HexagonLayer",
                  data=df.to_dict(orient="records"),
                  get_position='[lon, lat]',
                  radius=50000,
                  elevation_scale=40,
                  elevation_range=[0, 1000],
                  extruded=True,
                  coverage=1)

view_state = pdk.ViewState(latitude=0, longitude=0, zoom=1, pitch=40)

deck = pdk.Deck(layers=[layer], initial_view_state=view_state, map_style=None)

deck.to_html("orchid_atlas.html")

print("Atlas generated")
