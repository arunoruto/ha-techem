<a id="readme-top"></a>

[![HACS][hacs-shield]][hacs-url]
[![Release][release-shield]][release-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<br />
<div align="center">

<h3 align="center">Techem for Home Assistant</h3>

  <p align="center">
    Your monthly heating and water consumption from the Techem tenant portal, as sensors and long-term statistics.
    <br />
    <br />
    <a href="https://github.com/arunoruto/ha-techem/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/arunoruto/ha-techem/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>

> [!NOTE]
> **Unofficial.** Not affiliated with Techem. The portal has no public API, so this reads
> the same pages your browser does. It may break whenever Techem changes the portal.
> The integration's icon is an original design, not the Techem logo.

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#setup">Setup</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#sensors">Sensors</a></li>
        <li><a href="#history-and-the-energy-dashboard">History and the Energy dashboard</a></li>
        <li><a href="#staying-logged-in">Staying logged in</a></li>
      </ul>
    </li>
    <li>
      <a href="#the-heating-model">The heating model</a>
      <ul>
        <li><a href="#1-monthly-consumption-vs-weather">Monthly consumption vs weather</a></li>
        <li><a href="#2-behaviour-factor">Behaviour factor</a></li>
        <li><a href="#3-forecast-for-the-current-month">Forecast for the current month</a></li>
        <li><a href="#4-hourly-distribution">Hourly distribution</a></li>
        <li><a href="#configuration-and-privacy">Configuration and privacy</a></li>
      </ul>
    </li>
    <li><a href="#how-it-works">How it works</a></li>
    <li><a href="#limitations">Limitations</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



## About The Project

Tenants in Germany whose flats have Techem heat cost allocators or water meters get a
monthly consumption report ("Verbrauchsinfo", required by the EED and the HKVO) on
[mieter.techem.de](https://mieter.techem.de). This integration brings that data into
Home Assistant:

* **Sensors** for the last month per flat and service: heating, and hot/cold water if
  your flat has them. Also the same month last year, year to date, Techem's average for
  comparable households, and the kWh-per-unit factor.
* **The full monthly history** (the portal keeps about three years) as long-term
  statistics, ready for a *Statistics graph* card or the **Energy dashboard**.
* **No password stored.** You paste the portal's session cookie once; the integration
  keeps it renewed by itself.

Data arrives monthly, a few days after the month ends. Use it for trends and
year-on-year comparisons, not for real-time control.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

* [Home Assistant](https://www.home-assistant.io/) custom integration (config flow, `DataUpdateCoordinator`, recorder statistics)
* [aiohttp](https://docs.aiohttp.org/), already part of Home Assistant, so there are no extra requirements

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## Getting Started

### Prerequisites

* Home Assistant **2026.1** or newer
* An account on [mieter.techem.de](https://mieter.techem.de) with at least one flat

### Installation

**HACS (recommended)**

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/arunoruto/ha-techem` with type *Integration*.
2. Install **Techem** and restart Home Assistant.

**Manual**

Copy `custom_components/techem` into your `config/custom_components/` and restart Home Assistant.

### Setup

The portal logs in through Azure AD B2C on Techem's server and only hands the browser a
session cookie, so that cookie is what the integration needs:

1. Log in at [mieter.techem.de](https://mieter.techem.de).
2. Open the developer tools:
   * **Chrome / Edge:** F12 → *Application* → *Cookies* → `https://mieter.techem.de`
   * **Firefox:** F12 → *Storage* → *Cookies*
   * **Safari:** enable *Settings → Advanced → Show features for web developers*, then ⌥⌘I → *Storage* → *Cookies*
3. Copy the value of `__Secure-next-auth.session-token`. If it is split into `.0` / `.1`
   parts, paste the whole `Cookie:` request header instead.
4. *Settings → Devices & services → Add integration → Techem*, and paste it.

> [!IMPORTANT]
> Treat the cookie like a password: it gives read access to your portal account
> (consumption, name, address). The integration stores it only in its config entry.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## Usage

### Sensors

Each flat becomes a device, with these sensors per service:

| Sensor | Example | Notes |
|---|---|---|
| Heating last month | `310.5 kWh` | attributes: `period`, `status`, `quality`, `revision` |
| Heating last month (units) | `172 units` | raw heat cost allocator units (HCU) |
| Heating same month last year | `655.0 kWh` | |
| Heating year to date | `4210.4 kWh` | sum of this year's months so far |
| Heating comparable households | `701.3 kWh` | Techem's average for similar flats |
| Heating kWh per unit | `1.81 kWh/unit` | Techem's valuation factor for the month |
| Heating forecast this month | `640 kWh` | model forecast for the whole current month, see [the heating model](#the-heating-model) |
| Heating this month so far | `120 kWh` | model estimate until now |
| Heating last month vs weather | `85 %` | actual ÷ weather model for the newest month |
| Heating behaviour factor | `0.85` | diagnostic; attributes hold the fitted model parameters |

Water services get *last month* in m³ and, where Techem provides it, *comparable households*.

### History and the Energy dashboard

Every month the portal knows about is imported as an external statistic, e.g.
`techem:heating_kwh_<id>`:

* **Statistics graph card:** pick the statistic and set the period to *month*.
* **Energy dashboard:** *Gas consumption* → add *Techem Heating (kWh, monthly)*.

Each month is booked on its first hour. When Techem revises a month, the history is
corrected on the next poll.

A second statistic, `techem:heating_kwh_distributed_<id>` (*Techem Heating (kWh, hourly
estimate)*), spreads every month over its hours using weather or radiator valves (see
[the heating model](#4-hourly-distribution)) and includes an estimate for months Techem
hasn't published yet. Use this one in the Energy dashboard if you want meaningful day
and week views. Monthly totals are identical to Techem's.

### Staying logged in

The portal issues a fresh cookie on every visit. The integration polls every 6 hours and
saves the renewed cookie, so the session doesn't expire. If it ever does (for example
after you log out everywhere), Home Assistant shows a re-authentication prompt: paste a
fresh cookie.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## The heating model

Techem only publishes one number per month. To get a **forecast for the current month**
and an **hourly history** that the Energy dashboard can show per day, the integration
fits a small empirical model to your own history. Everything below is computed locally
in Home Assistant; the fitted numbers are exposed as attributes of the
*Heating behaviour factor* sensor, so you can always see what the model is doing.

### 1. Monthly consumption vs weather

For every month $m$ the integration computes, from hourly outdoor temperature $T_h$ and
global solar radiation $G_h$ (W/m²):

$$
\mathrm{HDD}_m(T_b) = \frac{1}{24}\sum_{h \in m} \max(0,\; T_b - T_h)
\qquad
\mathrm{SUN}_m(T_b) = \frac{1}{1000}\sum_{h \in m,\; T_h < T_b} G_h
$$

*heating degree days* above a balance temperature $T_b$, and the solar energy (kWh/m²)
that falls during hours that need heating. The model is a least-squares fit through the
origin:

$$
\boxed{\;E_m = a \cdot \mathrm{HDD}_m(T_b) + s \cdot \mathrm{SUN}_m(T_b)\;}
$$

* $a$ (kWh per degree day) is the flat's heat loss.
* $s$ is negative: sunshine through the windows replaces heating (solar gain). Without
  it, the model overestimates spring and underestimates autumn at the same temperature.
* $T_b$ is chosen from 14–24 °C in 0.5 K steps by the lowest **leave-one-out** error
  (each month predicted from all the others), so it is honest about accuracy.
* All months are used, including summer zeros: they anchor the fit.

The model is refitted on every poll, so it improves as months are added.

**Example: the author's flat (34 months, Jan 2024–Oct 2026)**

| | |
|---|---|
| Balance temperature $T_b$ | 18.5 °C |
| $a$ | 3.26 kWh / degree day |
| $s$ | −3.44 kWh per kWh/m² of sun |
| $R^2$ | 0.945 |
| Leave-one-out RMSE | 138 kWh / month |

Temperature alone gives $R^2 = 0.92$; adding sunshine brings it to 0.95. Wind did not
help (tested, not included).

### 2. Behaviour factor

The weather model describes an *average* year. How you heat (set points, schedules,
smart thermostats, being away) changes over time, so the forecast is scaled by a
behaviour factor from your most recent heating months:

$$
f = \frac{\sum_{m \in R} E^{\mathrm{actual}}_m + P}{\sum_{m \in R} E^{\mathrm{model}}_m + P}
$$

* $R$: the last up to 3 months within 4 months of the newest data where both actual and
  modelled consumption are at least 50 and 100 kWh (no bleed from last spring across the summer).
* $P = 100$ kWh is a prior that pulls $f$ towards 1 while there is little data.

$f < 1$ means you used less than the weather alone would predict. The sensor *Heating
last month vs weather* shows the raw ratio $E^{\mathrm{actual}}/E^{\mathrm{model}}$ for
the newest month, a weather-normalised way to judge savings.

### 3. Forecast for the current month

$$
\hat E_{\text{month}} = f \cdot \Big(\underbrace{\sum_{h \le \text{now}} e_h}_{\text{weather so far}}
+ \underbrace{\sum_{h > \text{now}} e_h}_{\text{16-day forecast}}
+ \underbrace{n_{\text{gap}} \cdot \bar e_{\text{past years}}}_{\text{beyond the forecast}}\Big)
$$

with the hourly model value
$e_h = \max\!\big(0,\; \tfrac{a}{24}\max(0, T_b - T_h) + s\,\tfrac{G_h}{1000}[T_h < T_b]\big)$.
Hours beyond the 16-day weather forecast use the average hourly value of the same
calendar month in previous years. Once Techem publishes the month (usually within the
first days of the next month), the actual value replaces the estimate, and $f$ is updated.

### 4. Hourly distribution

Each monthly total is spread over the hours of its month, so day and week views of the
Energy dashboard are meaningful. The month total always stays exactly Techem's value;
only the shape within the month is estimated. The method is chosen per month:

1. **Radiator valves**, if you selected valve sensors and they cover ≥ 80 % of the
   month's hours. Each radiator's heat output follows the radiator equation (EN 442):

   $$
   w_h = \sum_{r} \frac{v_{r,h}}{100}\,\big(T^{\text{flow}}_h - T^{\text{room}}_{r,h}\big)^{1.3},
   \qquad
   T^{\text{flow}}_h = \operatorname{clip}\big(20 + 1.17\,(20 - T_h),\; 25,\; 70\big)
   $$

   $v_{r,h}$ is the valve opening in %, $T^{\text{room}}$ the temperature sensor on the
   same device as the valve (e.g. the thermostat's own), and $T^{\text{flow}}$ a typical
   weather-compensated heating curve (55 °C at −10 °C, 32 °C at +10 °C).
2. **Weather**: $w_h = e_h$ from the monthly model.
3. **Even**: summer months, where the model expects less than 50 kWh.

$$
E_h = E_m \cdot \frac{w_h}{\sum_{h' \in m} w_{h'}}
$$

The months Techem hasn't published yet are estimated as $f \cdot e_h$ (split by the
valves if available) and replaced by the actual value later.

**What valves add:** in the author's flat, valve activity correlated only weakly with
outdoor temperature from day to day (r ≈ 0); it follows schedules, presence and the
thermostat's control. The weather model is good for the month **total**, the valves for
**when** within the month the heat was used.

### Configuration and privacy

*Settings → Devices & services → Techem → Configure*:

* **Use Open-Meteo weather** (default on): hourly temperature and solar radiation from
  [Open-Meteo](https://open-meteo.com) (free, no API key). Only your home coordinates
  **rounded to 0.1° (~10 km)** are sent. History is downloaded once and cached.
* **Radiator valve position sensors** (optional): sensors reporting valve opening in %.
  They need long-term statistics. If yours don't have a `state_class`, add it in
  `customize.yaml`:

  ```yaml
  sensor.living_room_thermostat_valve_position:
    state_class: measurement
  ```

### Model limitations

* It needs at least a few months of history, including some heating months.
* One flat-wide model: no per-room split yet. Valve-based room shares ignore radiator
  sizes until enough months exist to learn them.
* Hot water: if your hot water is billed by Techem as heating energy (central hot water),
  it ends up in the same model as a weather-independent base load the fit doesn't know
  about. The author's flat has electric hot water.
* The heating curve and radiator exponent are typical values, not measured.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## How it works

`mieter.techem.de` is a Next.js app. Its backend API (`/api/v1/...`) needs an API key
only the portal server has, so the integration fetches the rendered pages with your
session cookie and extracts the consumption records from the embedded React Server
Components payload:

```json
{"period": "2026-10", "service": "HEATING", "unitOfMeasure": "KWH", "status": "OK",
 "amount": 310.5, "quality": 1, "revision": 1, "mixedHeatingEquipment": false}
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## Limitations

* **Monthly flat totals only.** The portal has no per-radiator or per-room values and no
  daily data; the monthly total is all Techem publishes to tenants. Hourly values are
  model estimates (see [the heating model](#the-heating-model)).
* **No local alternative.** The radio telegrams of newer Techem devices are encrypted,
  so reading them locally with wM-Bus isn't an option.
* **Scraping.** A portal redesign can break the parser until the integration is updated.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## Contributing

Bug reports are most useful with the integration's debug log
(`logger: logs: custom_components.techem: debug`). Please remove cookies, names and
addresses before posting anything from the portal.

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a pull request

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



## Acknowledgments

* [mrueg/techem-scraper](https://github.com/mrueg/techem-scraper), which documented the earlier version of the portal API
* [Best-README-Template](https://github.com/othneildrew/Best-README-Template)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs-url]: https://hacs.xyz/docs/faq/custom_repositories/
[release-shield]: https://img.shields.io/github/v/release/arunoruto/ha-techem.svg?style=for-the-badge
[release-url]: https://github.com/arunoruto/ha-techem/releases
[issues-shield]: https://img.shields.io/github/issues/arunoruto/ha-techem.svg?style=for-the-badge
[issues-url]: https://github.com/arunoruto/ha-techem/issues
[license-shield]: https://img.shields.io/github/license/arunoruto/ha-techem.svg?style=for-the-badge
[license-url]: https://github.com/arunoruto/ha-techem/blob/main/LICENSE
