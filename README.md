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

Water services get *last month* in m³ and, where Techem provides it, *comparable households*.

### History and the Energy dashboard

Every month the portal knows about is imported as an external statistic, e.g.
`techem:heating_kwh_<id>`:

* **Statistics graph card:** pick the statistic and set the period to *month*.
* **Energy dashboard:** *Gas consumption* → add *Techem Heating (kWh, monthly)*.

Each month is booked on its first hour. When Techem revises a month, the history is
corrected on the next poll.

### Staying logged in

The portal issues a fresh cookie on every visit. The integration polls every 6 hours and
saves the renewed cookie, so the session doesn't expire. If it ever does (for example
after you log out everywhere), Home Assistant shows a re-authentication prompt: paste a
fresh cookie.

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
  daily data; the monthly total is all Techem publishes to tenants.
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
