# %%
# Python Standard Libraries
import os
import datetime as dt
import calendar
import zipfile
import urllib.request
from string import ascii_lowercase as ABC

# Data Manipulation Libraries
import numpy as np
import pandas as pd
import xarray as xr
import regionmask as rm
import dask

# Visualization Libraries
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.colors as mcolors
from matplotlib.gridspec import GridSpec
import matplotlib.dates as mdates
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from dask.diagnostics.progress import ProgressBar

# Climate Data Store API for retrieving climate data
import cdsapi


plt.style.use(
    "../copernicus.mplstyle"
)  # Set the visual style of the plots; not necessary for the tutorial


dask.config.set(**{"array.slicing.split_large_chunks": True})

# Boolean land-sea mask
lsm = rm.defined_regions.natural_earth_v5_0_0.land_110


# Define some parameters that can be easily changed
PROJS = {
    "Europe": ccrs.TransverseMercator(central_longitude=15, central_latitude=52),
    "Arctic": ccrs.Orthographic(central_longitude=0, central_latitude=90),
    "Global": ccrs.EqualEarth(),
    "Data": ccrs.PlateCarree(),
}

# %%
file_name = {}  # dictionary containing [data source : file name]

# Add the data sources and file names
file_name.update(
    {"berkeley": "temperature_berkeley.nc"}
)  # is not available as netCDF, only as zip file
file_name.update(
    {"gistemp": "temperature_gistemp.gz"}
)  # is not available as netCDF, only as zip file
file_name.update({"hadcrut": "temperature_hadcrut.nc"})
file_name.update({"era5": "temperature_era5.nc"})
file_name.update({"eobs": "temperature_eobs.tar.gz"})

# Create the paths to the files
path_to = {
    source: os.path.join(f"data/{source}/", file) for source, file in file_name.items()
}

# Create necessary directories if they do not exist
for path in path_to.values():
    os.makedirs(
        os.path.dirname(path), exist_ok=True
    )  # create the folder if not available

path_to


# %%
def coordinate_is_monthly(ds, coord: str = "time"):
    """Return True if the coordinates are months"""
    time_diffs = np.diff(ds.coords[coord].values)
    time_diffs = pd.to_timedelta(time_diffs).days

    # If all differences are between 28 and 31 days
    if np.all((28 <= time_diffs) & (time_diffs <= 31)):
        return True
    else:
        return False


def streamline_coords(da):
    """Streamline the coordinates of a DataArray.

    Parameters
    ----------
    da : xr.DataArray
        The DataArray to streamline.
    """

    # Ensure that time coordinate is fixed to the first day of the month
    if "time" in da.coords:
        if coordinate_is_monthly(da, "time"):
            da.coords["time"] = da["time"].to_index().to_period("M").to_timestamp()

    # Ensure that spatial coordinates are called 'lon' and 'lat'
    if "longitude" in da.coords:
        da = da.rename({"longitude": "lon"})
    if "latitude" in da.coords:
        da = da.rename({"latitude": "lat"})

    # Ensure that lon/lat are sorted in ascending order
    da = da.sortby("lat")
    da = da.sortby("lon")

    # Ensure that lon is in the range [-180, 180]
    lon_min = da["lon"].min()
    lon_max = da["lon"].max()
    if lon_min < -180 or lon_max > 180:
        da.coords["lon"] = (da.coords["lon"] + 180) % 360 - 180
        da = da.sortby(da.lon)

    return da


# %%
# Define regions of interest
# =============================================================================
# Some regions are defined here: https://climate.copernicus.eu/esotc/2022/about-data#Regiondefinitions
REGIONS = {
    "Global": {"lon": slice(-180, 180), "lat": slice(-90, 90)},
    "Northern Hemisphere": {"lon": slice(-180, 180), "lat": slice(0, 90)},
    "Southern Hemisphere": {"lon": slice(-180, 180), "lat": slice(-90, 0)},
    "Europe": {"lon": slice(-25, 40), "lat": slice(34, 72)},
    "Arctic": {"lon": slice(-180, 180), "lat": slice(66.6, 90)},
}

# Define climatology period
# =============================================================================
REF_PERIOD = {"time": slice("1991", "2020")}

MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
# %%
# Long term evolution of global mean temperature
# =============================================================================
# %%
# NOAA
url_to_noaa = "https://www.ncei.noaa.gov/thredds/dodsC/noaa-global-temp-v5.1/NOAAGlobalTemp_v5.1.0_gridded_s185001_e202306_c20230708T112624.nc"
noaa = xr.open_dataset(url_to_noaa)
noaa = noaa.isel(z=0, drop=True)
noaa = streamline_coords(noaa)
noaa["lsm"] = lsm.mask(noaa).notnull()

# %%
# Berkeley
berkeley = xr.open_dataset(path_to["berkeley"])
new_time_coords = xr.cftime_range(
    start="1850-01-01", periods=berkeley.time.size, freq="MS"
).to_datetimeindex()
berkeley.coords.update({"time": new_time_coords})
berkeley = streamline_coords(berkeley)
# %%
# GISTEMP
with xr.open_dataset("data/gistemp/temperature_gistemp_1200km.gz") as gistemp_1200:
    gistemp_1200 = gistemp_1200["tempanomaly"]
with xr.open_dataset("data/gistemp/temperature_gistemp_250km.gz") as gistemp_250:
    gistemp_250 = gistemp_250["tempanomaly"]
gistemp = gistemp_250.where(gistemp_250.notnull(), other=gistemp_1200)
gistemp_lsm = pd.read_csv(
    "data/gistemp/temperature_gistemp_land_sea_mask.txt",
    sep="\s+",
    header=1,
    names=["lon", "lat", "mask"],
)
gistemp_lsm = gistemp_lsm.set_index(["lat", "lon"])
gistemp_lsm = gistemp_lsm.to_xarray()
gistemp = xr.merge([gistemp, gistemp_lsm["mask"]])
gistemp = streamline_coords(gistemp)


# %%
# HadCRUT
with xr.open_dataset(path_to["hadcrut"]) as hadcrut:
    pass
with xr.open_dataset("data/hadcrut/temperature_weights.nc") as hadcrut_weights:
    pass
hadcrut_members = xr.open_mfdataset(
    "data/hadcrut/*analysis*.nc", combine="nested", concat_dim="realization"
)
hadcrut_members = hadcrut_members.compute()
hadcrut = xr.Dataset(
    {
        "mean": hadcrut["tas_mean"],
        "weights": hadcrut_weights["weights"],
        "ensemble": hadcrut_members["tas"],
    }
)
hadcrut = streamline_coords(hadcrut)

# %%
# ERA5
with xr.open_mfdataset(path_to["era5"]) as era5:
    # convert from Kelvin to Celsius
    era5["t2m"] = era5["t2m"] - 273.15
era5 = streamline_coords(era5)
era5_monthly_climatology = era5["t2m"].sel(REF_PERIOD).groupby("time.month").mean()
era5["anom"] = era5["t2m"].groupby("time.month") - era5_monthly_climatology


# %%


def weighted_spatial_average(da, region, land_mask=None):
    """Calculate the weighted spatial average of a DataArray.

    Parameters
    ----------
    da : xr.DataArray
        The DataArray to average.
    weights : xr.DataArray, optional
        A DataArray with the same dimensions as `da` containing the weights.
    """
    da = da.sel(**region)

    # Area weighting: calculate the area of each grid cell
    weights = np.cos(np.deg2rad(da.lat))

    # Additional user-specified weights, e.g. land-sea mask
    if land_mask is not None:
        land_mask = land_mask.sel(**region)
        weights = weights * land_mask.fillna(0)

    return da.weighted(weights).mean(("lat", "lon"))


# %%
# Spatial average of global temperature anomalies
# -----------------------------------------------------------------------------

region = "Arctic"

temps = {
    "HadCRUT": hadcrut["mean"],
    "HadCRUT_ensemble": hadcrut["ensemble"],
    "Berkeley": berkeley["temperature"],
    "GISTEMP": gistemp["tempanomaly"],
    "NOAA": noaa["anom"],
    "ERA5": era5["t2m"],
}
land_masks = {
    "HadCRUT": hadcrut["weights"],
    "HadCRUT_ensemble": hadcrut["weights"],
    "Berkeley": berkeley["land_mask"],
    "GISTEMP": gistemp["mask"],
    "NOAA": noaa["lsm"],
    "ERA5": era5["lsm"],
}

temp_evolution = {}
for source in temps:
    spatial_average = weighted_spatial_average(
        temps[source], REGIONS[region], land_masks[source]
    )
    with ProgressBar():
        temp_evolution[source] = spatial_average.compute()
temp_evolution = xr.Dataset(temp_evolution)

# Show anomalies with respect to the 1991-2020 climatology
temp_evolution = temp_evolution - temp_evolution.sel(REF_PERIOD).mean("time")

# %%
temp_evolution_smooth = temp_evolution.rolling(time=60, center=True).mean()

anom_1850_1900 = temp_evolution_smooth.drop_vars("HadCRUT_ensemble").sel(
    time=slice("1850", "1900")
)
mean_1850_1900 = anom_1850_1900.to_array().mean()

# %%
ci = temp_evolution_smooth["HadCRUT_ensemble"].quantile([0.0, 1.0], dim="realization")
# %%
fig = plt.figure(figsize=(10, 3))
ax = fig.add_subplot(111)
ax2 = ax.twinx()
temp_evolution_smooth["HadCRUT"].plot(ax=ax, label="HadCRUT")
temp_evolution_smooth["Berkeley"].plot(ax=ax, label="Berkeley")
temp_evolution_smooth["GISTEMP"].plot(ax=ax, label="GISTEMP")
temp_evolution_smooth["NOAA"].plot(ax=ax, label="NOAA")
temp_evolution_smooth["ERA5"].plot(ax=ax, label="ERA5")
ax.fill_between(
    ci.time,
    ci.sel(quantile=0.0),
    ci.sel(quantile=1.0),
    color=".7",
    alpha=0.5,
    lw=0,
    zorder=-1,
)
ax.legend(ncols=6, frameon=False, loc="upper center")


ax2.spines["right"].set_visible(True)
ax2.spines["top"].set_visible(True)
ax.xaxis.set_major_locator(mdates.YearLocator(20))

ax.set_xlabel("")
ax.set_ylabel("")
ax.set_title(f"{region} Mean Temperature Anomaly (in ºC) since 1850")
ax.text(
    -0.02,
    1,
    "Relative to \n1991-2020",
    rotation=0,
    ha="right",
    va="top",
    transform=ax.transAxes,
)
ax.text(
    1.02,
    1,
    "Increase above \n1850-1900\n reference level",
    rotation=0,
    ha="left",
    va="top",
    transform=ax.transAxes,
)
ax.axhline(mean_1850_1900, color=".5", lw=0.5, ls="--")

yticks = np.arange(-10, 10, 1)
ax2_yticks = yticks + mean_1850_1900.item()
ax2.set_yticks(ax2_yticks)
ax2.set_yticklabels(yticks)
ax.set_ylim(-4.1, 1.8)
ax2.set_ylim(-4.1, 1.8)

plt.show()

# %%
# Taking Earth's mean temperature
region = "Europe"
land_mask = era5["lsm"]
clim_temp_era5 = era5["t2m"].sel(REF_PERIOD)
clim_temp_era5 = weighted_spatial_average(
    clim_temp_era5, REGIONS[region], land_mask=land_mask
)

with ProgressBar():
    clim_temp_era5 = clim_temp_era5.compute()

# Weithed temporal mean taking into account the number of days in each month over climatology period
dim = clim_temp_era5.time.dt.days_in_month
clim_temp_era5 = (clim_temp_era5 * dim).sum() / dim.sum()
print(clim_temp_era5)
# %%
# ERA5 vs EOBS (observational data)
# =============================================================================
# %%
# Europe only
with ProgressBar():
    era5_europe = era5.sel(REGIONS["Europe"]).compute()

# %%
# Get EOBS
eobs_daily = xr.open_mfdataset("data/eobs/tg_ens_mean_0.25deg_reg_v27.0e.nc")
eobs_daily = streamline_coords(eobs_daily)

# %%
# Figure 1. Annual European land surface air temperature anomalies for
# 1950 to 2022, relative to the 1991–2020 reference period.
# =============================================================================
# Select the region of interest
eobs_daily_europe = eobs_daily.sel(REGIONS["Europe"])
# Convert EOBS to monthly
eobs_europe = eobs_daily_europe.resample(time="MS", skipna=False).mean("time")
with ProgressBar():
    eobs_europe = eobs_europe.compute()

# Calculate the monthly climatology
eobs_monthly_climatology = (
    eobs_europe["tg"].sel(REF_PERIOD).groupby("time.month").mean()
)
eobs_europe["anom"] = eobs_europe["tg"].groupby("time.month") - eobs_monthly_climatology
eobs_europe["climatology"] = eobs_monthly_climatology


# %%
def convert_coords_time_to_year_month(ds):
    """Convert the coordinates of a DataArray from "time" to ("year", "month")"""
    year = ds.time.dt.year
    month = ds.time.dt.month

    # assign new coords
    ds = ds.assign_coords(year=("time", year.data), month=("time", month.data))

    # reshape the array to (..., "month", "year")
    return ds.set_index(time=("year", "month")).unstack("time")


def weighted_annual_average(da):
    """Calculate the weighted annual average per year."""
    days_in_month = da.time.dt.days_in_month
    weights = (
        days_in_month.groupby("time.year") / days_in_month.groupby("time.year").sum()
    )
    nominator = (da * weights).resample({"time": "AS"}).sum(skipna=False)
    denominator = weights.resample({"time": "AS"}).sum()
    np.testing.assert_allclose(denominator, 1)
    return nominator / denominator


# Calculate the monthly climatology
def annual_anomalies(da, land_mask=None):
    # 1. Calculate the spatial average
    da = weighted_spatial_average(da, REGIONS["Europe"], land_mask)
    # 2. Calculate the weighted (per days in month) annual average
    waa = weighted_annual_average(da)
    # 3. Convert the coordinates from "time" to ("year", "month")
    return convert_coords_time_to_year_month(waa).sel(month=1, drop=True)


eobs_europe_anom = annual_anomalies(eobs_europe["anom"], land_mask=None)
era5_europe_anom = annual_anomalies(era5_europe["anom"], land_mask=era5_europe["lsm"])

eobs_europe_anom.name = "EOBS"
era5_europe_anom.name = "ERA5"


# %%
eobs_daily_mean = weighted_spatial_average(eobs_daily_europe["tg"], REGIONS["Europe"])

with ProgressBar():
    eobs_daily_mean = eobs_daily_mean.compute()


# %%
eobs_2022 = eobs_daily_mean.sel(time="2022").groupby("time.dayofyear").mean()

eobs_windowed = (
    eobs_daily_mean.sel(REF_PERIOD)
    .rolling(time=31, center=True)
    .construct("window_dim")
)
eobs_daily_quantiles = eobs_windowed.groupby("time.dayofyear").quantile(
    [0.1, 0.5, 0.9], dim=["time", "window_dim"]
)
lower, median, upper = eobs_daily_quantiles.sel(dayofyear=slice(1, 365)).transpose(
    "quantile", "dayofyear"
)

# %%
fig = plt.figure(figsize=(8, 6))
ax = fig.add_subplot(111)
eobs_daily_quantiles.sel(quantile=[0.1, 0.9]).plot.line(
    ax=ax, x="dayofyear", lw=1, color=".3"
)
ax.fill_between(
    median.dayofyear,
    eobs_2022.where(eobs_2022 >= median, median),
    median,
    color="red",
    alpha=0.3,
    lw=0,
    zorder=-1,
)
ax.fill_between(
    median.dayofyear,
    eobs_2022.where(eobs_2022 <= median, median),
    median,
    color="blue",
    alpha=0.3,
    lw=0,
    zorder=-1,
)

ax.fill_between(
    median.dayofyear,
    eobs_2022.where(eobs_2022 >= upper, upper),
    upper,
    color="red",
    alpha=0.7,
    lw=0,
    zorder=1,
    label="warmer than average",
)
ax.fill_between(
    median.dayofyear,
    eobs_2022.where(eobs_2022 <= lower, lower),
    lower,
    color="blue",
    alpha=0.7,
    lw=0,
    zorder=1,
    label="colder than average",
)

days_in_month_2022 = (
    eobs_daily_europe.time.dt.days_in_month.sel(time="2022")
    .resample({"time": "MS"})
    .mean()
)
ax.legend()
xticks = [0] + days_in_month_2022.cumsum().values.tolist()
xticklabels = [calendar.month_abbr[x % 12 + 1] for x in range(len(xticks))]
ax.set_xticks(xticks)
ax.set_xticklabels(xticklabels)
ax.set_ylim(-5, 25)
ax.set_xlabel("")
ax.set_ylabel("Temperature (ºC)")
ax.set_title("Daily temperature anomalies in Europe (2022) relative to 1991-2020")
sns.despine(ax=ax, offset=5, trim=True)


# %%
def barplot_temperature(da1, da2, title=""):
    # make red and blue colors for above and below zero
    clrs = sns.color_palette("Paired", n_colors=6)
    clrs_da1 = [clrs[0] if anom < 0 else clrs[4] for anom in da1.values]
    clrs_da2 = [clrs[1] if anom < 0 else clrs[5] for anom in da2.values]

    fig = plt.figure(figsize=(14, 5))
    ax = fig.add_subplot(111)
    ax.bar(
        da1.year,
        da1,
        color=clrs_da1,
        label=da1.name,
        zorder=1,
    )
    ax.bar(
        da2.year,
        da2,
        0.25,
        color=clrs_da2,
        label="ERA5",
        zorder=2,
    )
    # Add a annoation for both datasets pointing to the last bar at the right hand side
    # with text "ERA5" and "EOBS" respectively. The text should be in the same color as
    # the bar.
    da1_final_data = (da1[-1].year.item(), da1[-1].item())
    da2_final_data = (da2[-1].year.item(), da2[-1].item())
    ax.annotate(
        da1.name,
        xy=da2_final_data,
        xytext=(2023, 1.4),
        arrowprops=dict(arrowstyle="-|>", color=clrs[5]),
        color=clrs[4],
        ha="left",
        xycoords="data",
    )
    ax.annotate(
        da2.name,
        xy=da1_final_data,
        xytext=(2023, 0.3),
        color=clrs[5],
        arrowprops=dict(arrowstyle="-|>", color=clrs[4]),
        ha="left",
        xycoords="data",
    )
    ax.axhline(0, color=".5", lw=0.5, ls="--")
    ax.set_title(title)
    sns.despine(ax=ax, offset=5, trim=True)
    plt.show()


title = "European annual temperature anomalies (in ºC)"
barplot_temperature(eobs_europe_anom, era5_europe_anom, title)

# %%
diff = era5_europe_anom - eobs_europe_anom
clrs_diff = np.where(diff > 0, "tab:red", "tab:blue")

fig = plt.figure(figsize=(14, 5))
ax = fig.add_subplot(111)
ax.bar(
    diff.year,
    diff,
    color=clrs_diff,
    label="",
    alpha=0.5,
)
ax.axhline(0, color=".5", lw=0.5, ls="--")
ax.set_title("ERA5 tends to underestimate temperatures in Europe in the 50s and 60s")
# Make a annotation pointing to (-.25, "1965") with text "ERA5 underestimates"
ax.annotate(
    "Cold bias in the 50s and 60s between ~0.1 and 0.3 ºC",
    xy=(1966, -0.245),
    xytext=(1977, -0.3),
    # make a curved arrow
    arrowprops=dict(
        arrowstyle="-|>",
        connectionstyle="angle3,angleA=0,angleB=-30",
    ),
    ha="left",
    xycoords="data",
)
ax.set_ylabel("ERA5 - EOBS temperature anomaly (in ºC)")
sns.despine(ax=ax, offset=5, trim=True)


# %%
# Figure 2. Average surface air temperature anomaly for 2022,
# relative to the 1991–2020 reference period.
# =============================================================================

eobs_yearly_anoms = weighted_annual_average(eobs_europe["anom"])
era5_yearly_anoms = weighted_annual_average(era5_europe["anom"])

eobs_yearly_anoms = convert_coords_time_to_year_month(eobs_yearly_anoms).sel(month=1)
era5_yearly_anoms = convert_coords_time_to_year_month(era5_yearly_anoms).sel(month=1)

# %%
YEAR = 2022


def spatial_plot_temperature(da1, da2, year):
    proj = ccrs.Orthographic(central_longitude=10, central_latitude=45)
    fig = plt.figure(figsize=(14, 5))
    gs = GridSpec(1, 3, figure=fig, width_ratios=[1, 1, 0.05], wspace=0.02)
    ax1 = fig.add_subplot(gs[0, 0], projection=PROJS["Europe"])
    ax2 = fig.add_subplot(gs[0, 1], projection=PROJS["Europe"])
    cax = fig.add_subplot(gs[0, 2])
    for ax in [ax1, ax2]:
        ax.coastlines("50m", lw=0.5)
        ax.add_feature(cfeature.OCEAN, facecolor=".6")
        ax.add_feature(cfeature.LAND, facecolor=".8")
        ax.set_extent([-25, 40, 34, 72], crs=PROJS["Data"])

    levels = np.arange(-3, 3.5, 0.5)
    kwargs = dict(
        levels=levels,
        transform=PROJS["Data"],
        cmap="RdYlBu_r",
        cbar_kwargs=dict(label="Temperature anomaly (ºC)"),
    )
    da1.sel(year=year).plot(ax=ax1, cbar_ax=cax, **kwargs)
    da2.sel(year=year).plot(ax=ax2, cbar_ax=cax, **kwargs)

    da1_dist = da1.sel(year=year).stack(x=("lat", "lon")).dropna("x").values
    da2_dist = da2.sel(year=year).stack(x=("lat", "lon")).dropna("x").values
    cax.boxplot(
        np.concatenate([da1_dist, da2_dist]),
        vert=True,
        positions=[0.5],
        whis=(5, 95),
        widths=0.5,
        flierprops=dict(marker=".", markersize=1),
    )
    cax.set_xticks([])
    ax1.set_title(f"{da1.name} ({year})")
    ax2.set_title(f"{da2.name} ({year})")


# %%
eobs_yearly_anoms.name = "EOBS"
era5_yearly_anoms.name = "ERA5"
spatial_plot_temperature(eobs_yearly_anoms, era5_yearly_anoms, YEAR)

# %%

diff = era5_yearly_anoms - eobs_yearly_anoms.interp_like(era5_yearly_anoms)

levels = np.arange(-3, 3.5, 0.5)
kwargs = dict(
    levels=levels,
    transform=PROJS["Data"],
    cmap="RdYlBu_r",
    cbar_kwargs=dict(label="Temperature anomaly (ºC)"),
)
fig = plt.figure(figsize=(7, 5))
gs = GridSpec(1, 2, figure=fig, width_ratios=[1, 0.05], wspace=0.02)
ax1 = fig.add_subplot(gs[0, 0], projection=PROJS["Europe"])
cax = fig.add_subplot(gs[0, 1])
ax1.coastlines("50m", lw=0.5)
ax1.add_feature(cfeature.OCEAN, facecolor=".6")
ax1.add_feature(cfeature.LAND, facecolor=".8")
ax1.set_extent([-25, 40, 34, 72], crs=ccrs.PlateCarree())
diff.sel(year=YEAR).plot(ax=ax1, cbar_ax=cax, **kwargs)
ax1.set_title(f"Difference between ERA5 - EOBS  ({YEAR})")
dist = diff.sel(year=YEAR).stack(x=("lat", "lon")).dropna("x").values
cax.boxplot(
    dist,
    vert=True,
    positions=[0.5],
    whis=(5, 95),
    widths=0.5,
    flierprops=dict(marker=".", markersize=1),
)
plt.show()


# %%
# Figure 3a. European land surface air temperature anomalies
# for SEASONS, relative to the average for the 1991–2020 reference period.
# -----------------------------------------------------------------------------
def weighted_seasonal_average(ds):
    """Calculate the weighted seasonal average per year and grid point.

    Important: in case there are missing values in the data the weighted average will be wrong.
    """
    month_length = ds.time.dt.days_in_month
    ds_weighted_sum = (ds * month_length).resample(time="QS-DEC").sum(skipna=False)
    sum_of_weights = month_length.resample(time="QS-DEC").sum()
    return ds_weighted_sum / sum_of_weights


def convert_time_to_year_season(ds):
    """Convert the coordinates of a DataArray from "time" to ("year", "season")"""
    year = ds.time.dt.year
    season = ds.time.dt.season

    # assign new coords
    ds = ds.assign_coords(year=("time", year.data), season=("time", season.data))

    # reshape the array to (..., "season", "year")
    return ds.set_index(time=("year", "season")).unstack("time")


# %%
eobs_seasonal = weighted_seasonal_average(eobs_europe)
era5_seasonal = weighted_seasonal_average(era5_europe)

eobs_seasonal.coords.update({"time": eobs_seasonal.time + pd.Timedelta(days=31)})
era5_seasonal.coords.update({"time": era5_seasonal.time + pd.Timedelta(days=31)})

eobs_seasonal = convert_time_to_year_season(eobs_seasonal)
era5_seasonal = convert_time_to_year_season(era5_seasonal)

eobs_seasonal.loc[dict(season="DJF", year=[1950, 2023])] = np.nan
era5_seasonal.loc[dict(season="DJF", year=[1950, 2023])] = np.nan

# %%
eobs_seasonal_average = weighted_spatial_average(
    eobs_seasonal["anom"], REGIONS["Europe"]
)
era5_seasonal_average = weighted_spatial_average(
    era5_seasonal["anom"], REGIONS["Europe"], land_mask=era5_seasonal["lsm"]
)

# %%
eobs_seasonal_average.name = "EOBS"
era5_seasonal_average.name = "ERA5"

SEASON = "SON"

title = f"European {SEASON} temperature anomalies (in ºC)"
barplot_temperature(
    eobs_seasonal_average.sel(season=SEASON, drop=True),
    era5_seasonal_average.sel(season=SEASON, drop=True),
    title,
)

# %%
# Figure 4b. Surface air temperature anomalies for winter, spring, summer
# and autumn 2022, relative to the respective seasonal average for the
# 1991–2020 reference period.
# -----------------------------------------------------------------------------
eobs_seasonal_anom = eobs_seasonal["anom"].sel(season=SEASON)
era5_seasonal_anom = era5_seasonal["anom"].sel(season=SEASON)

eobs_seasonal_anom.name = "EOBS"
era5_seasonal_anom.name = "ERA5"

spatial_plot_temperature(
    eobs_seasonal_anom,
    era5_seasonal_anom,
    YEAR,
)


# %%
# Figure 5. Average surface air temperature anomalies for each month
# of 2022, relative to the respective monthly average for the 1991–2020
# reference period. Data source: ERA5. Credit: C3S/ECMWF.
# -----------------------------------------------------------------------------


def plot_monthly_overview(da, title, **kwargs):
    da = convert_coords_time_to_year_month(da)
    fig = plt.figure(figsize=(10, 10))
    gs = GridSpec(
        4, 4, figure=fig, wspace=0.02, hspace=0.02, width_ratios=[1, 1, 1, 0.05]
    )
    axes = [
        fig.add_subplot(gs[i // 3, i % 3], projection=PROJS["Europe"])
        for i in range(12)
    ]
    cax = fig.add_subplot(gs[:, 3])

    for ax, month in zip(axes, da.month.values):
        da.sel(month=month).plot(ax=ax, cbar_ax=cax, **kwargs)
        ax.set_title("")
        ax.coastlines("50m", lw=0.5)
        ax.add_feature(cfeature.OCEAN, facecolor=".6")
        ax.add_feature(cfeature.LAND, facecolor=".8")
        ax.text(
            0.02,
            0.98,
            calendar.month_name[month],
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=12,
            bbox=dict(facecolor="w", edgecolor="w", boxstyle="round", alpha=0.8),
        )

    fig.suptitle(title, y=0.91)


title = "Monthly surface air temperature anomalies in 2022 (in ºC)"
kwargs.update({"levels": np.arange(-6, 6.5, 1.0), "vmin": -6, "vmax": 6})
plot_monthly_overview(era5_europe["anom"].sel(time="2022"), title, **kwargs)

# %%
monthly_diffs = era5_europe["anom"].sel(time="2022") - eobs_europe["anom"].sel(
    time="2022"
).interp_like(era5_europe["anom"])
title = "Differences between ERA5 and EOBS in 2022 (in ºC)"
kwargs.update({"levels": np.arange(-6, 6.1, 1.0), "vmin": -6, "vmax": 6})
plot_monthly_overview(monthly_diffs, title, **kwargs)

# %%
# Climate bulletins
# =============================================================================
# %%
# Compute the most recent anomaly
with ProgressBar():
    era5_in_2022 = era5["anom"].isel(time=-1).compute()

month_name = pd.to_datetime(era5_in_2022.time.values).strftime("%B")

# %%
# Create the Monthly Bulletin
fig = plt.figure(figsize=(8, 2.8), dpi=120)
gs = GridSpec(
    3, 3, figure=fig, width_ratios=[2.2, 1, 0.05], height_ratios=[0.05, 1, 0.05]
)

# Add the axes
tax = fig.add_subplot(gs[0, 0])
bax = fig.add_subplot(gs[2, 0])
ax1 = fig.add_subplot(gs[1, 0], projection=PROJS["Global"])
ax2 = fig.add_subplot(gs[1, 1], projection=PROJS["Europe"])
cax = fig.add_subplot(gs[1, 2])

# Set the extent of the maps
ax1.set_global()
ax2.set_extent([-13, 46, 35, 82], crs=PROJS["Data"])

# Add coastlines and anomlies
for ax in [ax1, ax2]:
    ax.coastlines(lw=0.5, color=".3")
    era5_in_2022.plot(ax=ax, cbar_ax=cax, **kwargs)

# Add titles, labels and text
ax1.set_title("A | Global")
ax2.set_title("B | Europe")

title = f"Surface air temperature anomaly for {month_name} 2022"
tax.set_title(title)
tax.text(0, 0, "in °C", ha="left", va="bottom", transform=tax.transAxes)
tax.axis("off")
bax.axis("off")
ref_start = REF_PERIOD["time"].start
ref_end = REF_PERIOD["time"].stop
bax.text(
    0,
    0,
    f"Reference period: {ref_start}-{ref_end}",
    ha="left",
    va="bottom",
    transform=bax.transAxes,
)
fig.subplots_adjust(bottom=0.0, hspace=0.02)
plt.show()

# %%
# Running twelve-month averages of global-mean and European-mean
# surface air temperature anomalies relative to 1991-2020
# -----------------------------------------------------------------------------
era5_satellite = era5["anom"].sel(time=slice("1979", None))
era5_global_mean = weighted_spatial_average(
    era5_satellite, REGIONS["Global"], land_mask=None
)
era5_europe_mean = weighted_spatial_average(
    era5_satellite, REGIONS["Europe"], era5["lsm"]
)
era5_arctic_mean = weighted_spatial_average(
    era5_satellite, REGIONS["Arctic"], era5["lsm"]
)

with ProgressBar():
    era5_global_mean = era5_global_mean.compute()
    era5_europe_mean = era5_europe_mean.compute()
    era5_arctic_mean = era5_arctic_mean.compute()

# %%
# Figure
# -----------------------------------------------------------------------------

era5_global_mean_smooth = era5_global_mean.rolling(time=12, center=True).mean()
era5_europe_mean_smooth = era5_europe_mean.rolling(time=12, center=True).mean()
era5_arctic_mean_smooth = era5_arctic_mean.rolling(time=12, center=True).mean()

fig = plt.figure(figsize=(9, 12), dpi=120)
gs = GridSpec(4, 1, figure=fig, height_ratios=[0.05, 1, 1, 1], hspace=0.25)

tax = fig.add_subplot(gs[0, 0])
axes = [fig.add_subplot(gs[i, 0]) for i in range(1, 4)]


def add_time_series(da, ax):
    ax.fill_between(
        da.time,
        da.where(da > 0, 0).values,
        color="red",
        alpha=0.5,
    )
    ax.fill_between(
        da.time,
        da.where(da < 0, 0).values,
        color="blue",
        alpha=0.5,
    )


add_time_series(era5_global_mean_smooth, axes[0])
add_time_series(era5_europe_mean_smooth, axes[1])
add_time_series(era5_arctic_mean_smooth, axes[2])

# Add annotations describing the data
desc_global = "Record high global \ntemperatures in 2015/16 \nwere partly due to \nstrong El Nino conditions."
desc_artic = "Arctic amplification leads to a warming rate of almost four times the global average.\nOne of the reasons is the ice-albedo feedack."
axes[0].annotate(
    desc_global,
    xy=(dt.datetime(2016, 1, 1), 0.4),
    xytext=(0.05, 0.9),
    textcoords=axes[0].transAxes,
    ha="left",
    va="top",
    arrowprops=dict(arrowstyle="->", color=".4", connectionstyle="arc3,rad=-0.2"),
)
axes[2].text(0.05, 0.9, desc_artic, transform=axes[2].transAxes, ha="left", va="top")

titles = ["Global", "Europe", "Arctic"]
for i, ax in enumerate(axes):
    ax.set_ylim(-3, 2)
    ax.axhline(0, color="k", ls="--", lw=0.5)
    ax.set_title(f"{ABC[i]} | {titles[i]}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
tax.axis("off")
tax.set_title("Surface air temperature anomalies", fontsize="x-large")
tax.text(0, 0, "in °C", ha="left", va="bottom", transform=tax.transAxes)
ref_start = REF_PERIOD["time"].start
ref_end = REF_PERIOD["time"].stop
tax.text(
    1,
    0,
    f"Reference period: {ref_start}-{ref_end}",
    ha="right",
    va="bottom",
    transform=tax.transAxes,
)

sns.despine(fig, trim=True)
