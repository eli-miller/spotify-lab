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
    "bpm",
    "speechiness",
    "instrumentalness",
    "release_year",
]
META_COLS = ["spotify_id", "name", "artist", "mood", "genre", "added_at"]

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
plt.suptitle("Shazam tracks — feature pairplot (essentia_preview, n=250)", y=1.02)
plt.tight_layout()
plt.show()

# %%
# --- Pairplot: shared features coloured by source ---
SHARED_COLS = [
    "bpm",
    "danceability",
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
# --- Clustering setup: scale features ---
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

feat_clean = features.dropna(subset=FEATURE_COLS).copy()
scaler = StandardScaler()
X = scaler.fit_transform(feat_clean[FEATURE_COLS])
print(f"Clustering on {X.shape[0]} tracks × {X.shape[1]} features")

# %%
# --- Elbow + silhouette — pick k ---
K_range = range(2, 9)
inertias, silhouettes = [], []
for k in K_range:
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    inertias.append(km.inertia_)
    silhouettes.append(silhouette_score(X, labels))

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
ax1.plot(list(K_range), inertias, marker="o")
ax1.set(xlabel="k", ylabel="Inertia", title="Elbow")
ax2.plot(list(K_range), silhouettes, marker="o")
ax2.set(xlabel="k", ylabel="Silhouette score", title="Silhouette")
plt.tight_layout()
plt.show()

# %%
# --- Fit k-means with chosen k ---
K = 2  # adjust after inspecting elbow/silhouette above
km = KMeans(n_clusters=K, random_state=42, n_init=10)
feat_clean["cluster"] = km.fit_predict(X)
print(feat_clean["cluster"].value_counts().sort_index())

# %%
# --- Cluster characterization ---
print("Mean features per cluster (original scale):")
print(feat_clean.groupby("cluster")[FEATURE_COLS].mean().round(3).to_string())
print()
print("Mood distribution per cluster:")
print(
    feat_clean.groupby("cluster")["mood"]
    .value_counts()
    .unstack(fill_value=0)
    .to_string()
)

# %%
# --- PCA 2D scatter (post-hoc visualization only) ---
pca_coords = PCA(n_components=2).fit_transform(X)
fig, ax = plt.subplots(figsize=(9, 7))
palette = sns.color_palette("tab10", K)
for c in range(K):
    mask = feat_clean["cluster"] == c
    ax.scatter(
        pca_coords[mask, 0],
        pca_coords[mask, 1],
        color=palette[c],
        alpha=0.7,
        s=60,
        label=f"Cluster {c}",
    )
ax.set(xlabel="PC1", ylabel="PC2", title=f"K-means clusters (k={K}) — PCA projection")
ax.legend()
plt.tight_layout()
plt.show()

# %%
# --- Pairplot: feature space coloured by cluster ---
import numpy as np

sns.pairplot(
    feat_clean.assign(cluster=feat_clean["cluster"].astype(str)),
    vars=FEATURE_COLS,
    hue="cluster",
    plot_kws={"alpha": 0.6, "s": 40},
    diag_kind="kde",
    corner=True,
)
plt.suptitle(f"Feature pairplot by cluster (k={K})", y=1.02)
plt.tight_layout()
plt.show()

# %%
# --- Radar chart: cluster centroid "personality" (standardised scale) ---
angles = np.linspace(0, 2 * np.pi, len(FEATURE_COLS), endpoint=False).tolist()
angles += angles[:1]  # close polygon

fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
palette = sns.color_palette("tab10", K)
for c in range(K):
    vals = km.cluster_centers_[c].tolist()
    vals += vals[:1]
    ax.plot(angles, vals, color=palette[c], linewidth=2, label=f"Cluster {c}")
    ax.fill(angles, vals, color=palette[c], alpha=0.12)
ax.set_xticks(angles[:-1])
ax.set_xticklabels(FEATURE_COLS, size=9)
ax.set_title(f"Cluster centroids — standardized features (k={K})", pad=20)
ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1))
plt.tight_layout()
plt.show()

# %%
# --- Silhouette plot: per-track confidence, grouped by cluster ---
from sklearn.metrics import silhouette_samples

sil_vals = silhouette_samples(X, feat_clean["cluster"])
fig, ax = plt.subplots(figsize=(8, 5))
y_lower = 0
for c in range(K):
    c_sil = np.sort(sil_vals[feat_clean["cluster"] == c])
    y_upper = y_lower + len(c_sil)
    ax.fill_betweenx(
        np.arange(y_lower, y_upper),
        0,
        c_sil,
        facecolor=palette[c],
        alpha=0.7,
        label=f"Cluster {c}",
    )
    ax.text(-0.05, y_lower + len(c_sil) / 2, str(c), va="center")
    y_lower = y_upper + 4

avg = sil_vals.mean()
ax.axvline(x=avg, color="black", linestyle="--", linewidth=1, label=f"Avg {avg:.3f}")
ax.set(
    xlabel="Silhouette coefficient",
    ylabel="",
    yticks=[],
    title=f"Silhouette plot (k={K}) — tracks left of 0 are likely mis-clustered",
)
ax.legend()
plt.tight_layout()
plt.show()

# %%
# --- Save model, scaler, and cluster assignments ---
import joblib

MODEL_DIR = Path(__file__).parent / f"model_k{K}"
MODEL_DIR.mkdir(exist_ok=True)

joblib.dump(km, MODEL_DIR / "kmeans.joblib")
joblib.dump(scaler, MODEL_DIR / "scaler.joblib")


def _centroid_description(cluster_idx):
    center = scaler.inverse_transform([km.cluster_centers_[cluster_idx]])[0]
    parts = []
    for col, val in zip(FEATURE_COLS, center):
        if col == "bpm":
            parts.append(f"bpm={val:.0f}")
        elif col == "release_year":
            parts.append(f"yr={val:.0f}")
        else:
            parts.append(f"{col[:5]}={val:.2f}")
    mask = feat_clean["cluster"] == cluster_idx
    top_moods = feat_clean.loc[mask, "mood"].value_counts().head(2)
    mood_str = " ".join(f"{m}({n})" for m, n in top_moods.items())
    n = int(mask.sum())
    return f"{' '.join(parts)} · {mood_str} · {n} tracks"


state = {
    "cluster_meta": {
        "k": K,
        "feature_cols": FEATURE_COLS,
        "playlist_ids": {},  # populated by create_playlists.py on first run
        "descriptions": {str(c): _centroid_description(c) for c in range(K)},
    },
    "assignments": {},
}

for _, row in feat_clean.iterrows():
    state["assignments"][row["spotify_id"]] = int(row["cluster"])

ep_ids = set(feat_clean["spotify_id"])
for r in json.loads(DATA.read_text()):
    if r["spotify_id"] not in ep_ids:
        state["assignments"][r["spotify_id"]] = "other"

ASSIGNMENTS = Path(__file__).parent / f"cluster_assignments_k{K}.json"
ASSIGNMENTS.write_text(json.dumps(state, indent=2))
print(f"Saved model → {MODEL_DIR}/")
print(f"Saved assignments → {ASSIGNMENTS} ({len(state['assignments'])} tracks)")

# %%
