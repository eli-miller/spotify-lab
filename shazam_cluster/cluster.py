# %%
import json
import pandas as pd
import matplotlib

matplotlib.use("qt5agg")  # Use the Qt5Agg backend for interactive plotting
import matplotlib.pyplot as plt

plt.ion()  # Enable interactive mode
import seaborn as sns
from pathlib import Path


pd.set_option("display.max_columns", None)
pd.set_option("display.max_rows", 40)

DATA = Path(__file__).parent / "tracks.json"

# %%
# --- Full dataset ---
df = pd.DataFrame(json.loads(DATA.read_text()))
df["added_at"] = pd.to_datetime(df["added_at"])
# release_date arrives as YYYY-MM-DD, YYYY-MM, or YYYY — slice year and cast
df["release_year"] = df["release_date"].str[:4].astype(float)

print(df.shape)
df.head()

# %%
# --- Data quality ---
print("feature_source:\n", df["feature_source"].value_counts(dropna=False), "\n")
print("backfill_status:\n", df["backfill_status"].value_counts(dropna=False))

# %%
# --- Feature DataFrame (essentia_preview only) ---
FEATURE_COLS = [
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "bpm",
    "release_year",
]
META_COLS = ["name", "artist", "mood", "genre", "added_at"]

ep = df[df["feature_source"] == "essentia_preview"].reset_index(drop=True)
features = ep[META_COLS + FEATURE_COLS].copy()

print(f"{len(features)} tracks with complete features\n")
features[FEATURE_COLS].describe().round(3)

# %%
# --- Combined DataFrame: essentia_preview + acousticbrainz (114 tracks) ---
# acousticbrainz rows have NaN for energy and valence — all other feature cols populated.
# msd excluded (energy=0.0 is a placeholder, not a real value).
combined = (
    df[df["feature_source"].isin(["essentia_preview", "acousticbrainz"])].reset_index(
        drop=True
    )
)[META_COLS + ["feature_source"] + FEATURE_COLS].copy()

print(
    f"{len(combined)} tracks  ({combined['feature_source'].value_counts().to_dict()})\n"
)
print("NaN counts per feature:")
print(combined[FEATURE_COLS].isna().sum().to_string())
print()
combined[FEATURE_COLS].describe().round(3)

# %%
# --- Pairplot: feature relationships coloured by FreqBlog mood label ---
sns.pairplot(
    features,
    vars=FEATURE_COLS,
    hue="mood",
    plot_kws={"alpha": 0.7, "s": 60},
    diag_kind="kde",
    corner=True,
)
plt.suptitle("Shazam tracks — feature pairplot (essentia_preview, n=74)", y=1.02)
plt.tight_layout()
plt.show()

# %%
# --- Pairplot: shared features coloured by source ---
SHARED_COLS = [
    "bpm",
    "danceability",
    "acousticness",
    "instrumentalness",
    "release_year",
]

sns.pairplot(
    combined.dropna(subset=SHARED_COLS),
    vars=SHARED_COLS,
    hue="feature_source",
    plot_kws={"alpha": 0.7, "s": 60},
    diag_kind="kde",
    corner=True,
)
plt.suptitle(
    "Shared features by source (essentia_preview + acousticbrainz, n=114)", y=1.02
)
plt.tight_layout()
plt.show()

# %%
