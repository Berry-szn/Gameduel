"""
Geography quiz pool — large.

Sub-modes:
  - FLAGS:     show a flag image, type the country
  - CAPITALS:  show a country, pick the capital (multiple choice)
  - LANDMARKS: show a landmark image, identify it
  - CONTINENTS: show a country, pick the continent

Flag images use https://flagcdn.com (free, hotlink-allowed CDN, ISO 3166-1
alpha-2 country codes). Historical / Legend-tier flags use Wikipedia Commons
since flagcdn only covers current sovereign states.

Difficulty tiers:
  easy   - very well-known countries
  medium - moderately well-known
  hard   - obscure / small / less-recognised
  legend - historical flags, empires, microstates, unrecognised states
"""

# ============================================================
# FLAGS — (country_name, iso2_code, difficulty)
# Image URL is built as https://flagcdn.com/w320/{iso2_lower}.png
# ============================================================

# Format: (display_name, iso2, difficulty)
FLAGS_DATA = [
    # ========== EASY (~60) ==========
    ('United States', 'us', 'easy'),
    ('United Kingdom', 'gb', 'easy'),
    ('France', 'fr', 'easy'),
    ('Germany', 'de', 'easy'),
    ('Italy', 'it', 'easy'),
    ('Spain', 'es', 'easy'),
    ('Japan', 'jp', 'easy'),
    ('China', 'cn', 'easy'),
    ('Brazil', 'br', 'easy'),
    ('Canada', 'ca', 'easy'),
    ('Mexico', 'mx', 'easy'),
    ('Russia', 'ru', 'easy'),
    ('India', 'in', 'easy'),
    ('Australia', 'au', 'easy'),
    ('South Africa', 'za', 'easy'),
    ('Argentina', 'ar', 'easy'),
    ('Nigeria', 'ng', 'easy'),
    ('Egypt', 'eg', 'easy'),
    ('Sweden', 'se', 'easy'),
    ('Netherlands', 'nl', 'easy'),
    ('Greece', 'gr', 'easy'),
    ('South Korea', 'kr', 'easy'),
    ('Turkey', 'tr', 'easy'),
    ('Portugal', 'pt', 'easy'),
    ('Ireland', 'ie', 'easy'),
    ('Norway', 'no', 'easy'),
    ('Switzerland', 'ch', 'easy'),
    ('Belgium', 'be', 'easy'),
    ('Denmark', 'dk', 'easy'),
    ('Finland', 'fi', 'easy'),
    ('Poland', 'pl', 'easy'),
    ('Austria', 'at', 'easy'),
    ('New Zealand', 'nz', 'easy'),
    ('Israel', 'il', 'easy'),
    ('Saudi Arabia', 'sa', 'easy'),
    ('Indonesia', 'id', 'easy'),
    ('Thailand', 'th', 'easy'),
    ('Vietnam', 'vn', 'easy'),
    ('Chile', 'cl', 'easy'),
    ('Colombia', 'co', 'easy'),
    ('Peru', 'pe', 'easy'),
    ('Singapore', 'sg', 'easy'),
    ('Malaysia', 'my', 'easy'),
    ('Philippines', 'ph', 'easy'),
    ('Kenya', 'ke', 'easy'),
    ('Ghana', 'gh', 'easy'),
    ('Morocco', 'ma', 'easy'),
    ('Iran', 'ir', 'easy'),
    ('Iraq', 'iq', 'easy'),
    ('Ukraine', 'ua', 'easy'),
    ('Cuba', 'cu', 'easy'),
    ('Jamaica', 'jm', 'easy'),
    ('Pakistan', 'pk', 'easy'),
    ('Czech Republic', 'cz', 'easy'),
    ('Hungary', 'hu', 'easy'),
    ('Romania', 'ro', 'easy'),
    ('Iceland', 'is', 'easy'),
    ('Venezuela', 've', 'easy'),
    ('United Arab Emirates', 'ae', 'easy'),
    ('Ethiopia', 'et', 'easy'),

    # ========== MEDIUM (~60) ==========
    ('Algeria', 'dz', 'medium'),
    ('Tunisia', 'tn', 'medium'),
    ('Libya', 'ly', 'medium'),
    ('Sudan', 'sd', 'medium'),
    ('Tanzania', 'tz', 'medium'),
    ('Uganda', 'ug', 'medium'),
    ('Zimbabwe', 'zw', 'medium'),
    ('Mozambique', 'mz', 'medium'),
    ('Angola', 'ao', 'medium'),
    ('Cameroon', 'cm', 'medium'),
    ('Senegal', 'sn', 'medium'),
    ('Rwanda', 'rw', 'medium'),
    ('Madagascar', 'mg', 'medium'),
    ('Bolivia', 'bo', 'medium'),
    ('Ecuador', 'ec', 'medium'),
    ('Uruguay', 'uy', 'medium'),
    ('Paraguay', 'py', 'medium'),
    ('Panama', 'pa', 'medium'),
    ('Costa Rica', 'cr', 'medium'),
    ('Guatemala', 'gt', 'medium'),
    ('Honduras', 'hn', 'medium'),
    ('Nicaragua', 'ni', 'medium'),
    ('Dominican Republic', 'do', 'medium'),
    ('Bangladesh', 'bd', 'medium'),
    ('Sri Lanka', 'lk', 'medium'),
    ('Nepal', 'np', 'medium'),
    ('Mongolia', 'mn', 'medium'),
    ('Kazakhstan', 'kz', 'medium'),
    ('Uzbekistan', 'uz', 'medium'),
    ('Azerbaijan', 'az', 'medium'),
    ('Georgia', 'ge', 'medium'),
    ('Armenia', 'am', 'medium'),
    ('Belarus', 'by', 'medium'),
    ('Estonia', 'ee', 'medium'),
    ('Latvia', 'lv', 'medium'),
    ('Lithuania', 'lt', 'medium'),
    ('Bulgaria', 'bg', 'medium'),
    ('Serbia', 'rs', 'medium'),
    ('Croatia', 'hr', 'medium'),
    ('Slovakia', 'sk', 'medium'),
    ('Slovenia', 'si', 'medium'),
    ('Bosnia and Herzegovina', 'ba', 'medium'),
    ('Albania', 'al', 'medium'),
    ('North Macedonia', 'mk', 'medium'),
    ('Cyprus', 'cy', 'medium'),
    ('Malta', 'mt', 'medium'),
    ('Luxembourg', 'lu', 'medium'),
    ('Jordan', 'jo', 'medium'),
    ('Lebanon', 'lb', 'medium'),
    ('Syria', 'sy', 'medium'),
    ('Yemen', 'ye', 'medium'),
    ('Oman', 'om', 'medium'),
    ('Qatar', 'qa', 'medium'),
    ('Kuwait', 'kw', 'medium'),
    ('Bahrain', 'bh', 'medium'),
    ('Cambodia', 'kh', 'medium'),
    ('Laos', 'la', 'medium'),
    ('Myanmar', 'mm', 'medium'),
    ('Afghanistan', 'af', 'medium'),
    ('Fiji', 'fj', 'medium'),

    # ========== HARD (~60) ==========
    ('Bhutan', 'bt', 'hard'),
    ('Eritrea', 'er', 'hard'),
    ('Djibouti', 'dj', 'hard'),
    ('Somalia', 'so', 'hard'),
    ('Burundi', 'bi', 'hard'),
    ('Malawi', 'mw', 'hard'),
    ('Zambia', 'zm', 'hard'),
    ('Botswana', 'bw', 'hard'),
    ('Namibia', 'na', 'hard'),
    ('Lesotho', 'ls', 'hard'),
    ('Eswatini', 'sz', 'hard'),
    ('Mali', 'ml', 'hard'),
    ('Niger', 'ne', 'hard'),
    ('Chad', 'td', 'hard'),
    ('Burkina Faso', 'bf', 'hard'),
    ('Sierra Leone', 'sl', 'hard'),
    ('Liberia', 'lr', 'hard'),
    ('Togo', 'tg', 'hard'),
    ('Benin', 'bj', 'hard'),
    ('Gabon', 'ga', 'hard'),
    ('Equatorial Guinea', 'gq', 'hard'),
    ('Congo', 'cg', 'hard'),
    ('DR Congo', 'cd', 'hard'),
    ('Central African Republic', 'cf', 'hard'),
    ('South Sudan', 'ss', 'hard'),
    ('Mauritania', 'mr', 'hard'),
    ('Gambia', 'gm', 'hard'),
    ('Guinea', 'gn', 'hard'),
    ('Guinea-Bissau', 'gw', 'hard'),
    ('Cabo Verde', 'cv', 'hard'),
    ('Comoros', 'km', 'hard'),
    ('Seychelles', 'sc', 'hard'),
    ('Mauritius', 'mu', 'hard'),
    ('Sao Tome and Principe', 'st', 'hard'),
    ('Kyrgyzstan', 'kg', 'hard'),
    ('Tajikistan', 'tj', 'hard'),
    ('Turkmenistan', 'tm', 'hard'),
    ('Moldova', 'md', 'hard'),
    ('Montenegro', 'me', 'hard'),
    ('Kosovo', 'xk', 'hard'),
    ('Liechtenstein', 'li', 'hard'),
    ('Monaco', 'mc', 'hard'),
    ('Andorra', 'ad', 'hard'),
    ('San Marino', 'sm', 'hard'),
    ('Vatican City', 'va', 'hard'),
    ('Brunei', 'bn', 'hard'),
    ('East Timor', 'tl', 'hard'),
    ('Papua New Guinea', 'pg', 'hard'),
    ('Vanuatu', 'vu', 'hard'),
    ('Solomon Islands', 'sb', 'hard'),
    ('Samoa', 'ws', 'hard'),
    ('Tonga', 'to', 'hard'),
    ('Kiribati', 'ki', 'hard'),
    ('Tuvalu', 'tv', 'hard'),
    ('Nauru', 'nr', 'hard'),
    ('Palau', 'pw', 'hard'),
    ('Micronesia', 'fm', 'hard'),
    ('Marshall Islands', 'mh', 'hard'),
    ('Maldives', 'mv', 'hard'),
    ('Suriname', 'sr', 'hard'),
    ('Guyana', 'gy', 'hard'),
    ('Belize', 'bz', 'hard'),
    ('Bahamas', 'bs', 'hard'),
    ('Barbados', 'bb', 'hard'),
    ('Trinidad and Tobago', 'tt', 'hard'),
    ('Saint Lucia', 'lc', 'hard'),
    ('Grenada', 'gd', 'hard'),
    ('Dominica', 'dm', 'hard'),
    ('Saint Vincent and the Grenadines', 'vc', 'hard'),
    ('Antigua and Barbuda', 'ag', 'hard'),
    ('Saint Kitts and Nevis', 'kn', 'hard'),
    ('Haiti', 'ht', 'hard'),
]

# ========== LEGEND (~25) ==========
# Historical flags, empires, microstates, unrecognised states.
# Uses Wikipedia Commons (flagcdn doesn't cover these).
LEGEND_FLAGS_DATA = [
    ('Soviet Union',         'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_the_Soviet_Union.svg?width=320', 'legend'),
    ('East Germany',         'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_East_Germany.svg?width=320', 'legend'),
    ('Yugoslavia',           'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Yugoslavia_(1946-1992).svg?width=320', 'legend'),
    ('Czechoslovakia',       'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Czechoslovakia.svg?width=320', 'legend'),
    ('Ottoman Empire',       'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_the_Ottoman_Empire.svg?width=320', 'legend'),
    ('Austria-Hungary',      'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Austria-Hungary_1869-1918.svg?width=320', 'legend'),
    ('Persian Empire',       'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Iran_(1933-1964).svg?width=320', 'legend'),
    ('Republic of Texas',    'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Texas.svg?width=320', 'legend'),
    ('Confederate States',   'https://commons.wikimedia.org/wiki/Special:FilePath/Confederate_National_Flag_since_Mar_4_1865.svg?width=320', 'legend'),
    ('Kingdom of Hawaii',    'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Hawaii.svg?width=320', 'legend'),
    ('Tibet',                'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Tibet.svg?width=320', 'legend'),
    ('Catalonia',            'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Catalonia.svg?width=320', 'legend'),
    ('Scotland',             'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Scotland.svg?width=320', 'legend'),
    ('Wales',                'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Wales.svg?width=320', 'legend'),
    ('Basque Country',       'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_the_Basque_Country.svg?width=320', 'legend'),
    ('Taiwan',               'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_the_Republic_of_China.svg?width=320', 'legend'),
    ('Hong Kong',            'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Hong_Kong.svg?width=320', 'legend'),
    ('Palestine',            'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Palestine.svg?width=320', 'legend'),
    ('Greenland',            'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Greenland.svg?width=320', 'legend'),
    ('Faroe Islands',        'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_the_Faroe_Islands.svg?width=320', 'legend'),
    ('Puerto Rico',          'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Puerto_Rico.svg?width=320', 'legend'),
    ('Bermuda',              'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Bermuda.svg?width=320', 'legend'),
    ('Anguilla',             'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_Anguilla.svg?width=320', 'legend'),
    ('Cook Islands',         'https://commons.wikimedia.org/wiki/Special:FilePath/Flag_of_the_Cook_Islands.svg?width=320', 'legend'),
]

# Build the unified FLAGS list with image URLs
FLAGS = []
for (name, iso, diff) in FLAGS_DATA:
    FLAGS.append((name, f'https://flagcdn.com/w320/{iso.lower()}.png', diff))
for entry in LEGEND_FLAGS_DATA:
    FLAGS.append(entry)


# ============================================================
# CAPITALS — (country, capital, continent, difficulty)
# Used for CAPITALS and CONTINENTS sub-modes.
# ============================================================

COUNTRIES_DATA = [
    # Africa
    ('Nigeria', 'Abuja', 'Africa', 'easy'),
    ('Egypt', 'Cairo', 'Africa', 'easy'),
    ('South Africa', 'Pretoria', 'Africa', 'medium'),
    ('Kenya', 'Nairobi', 'Africa', 'easy'),
    ('Morocco', 'Rabat', 'Africa', 'medium'),
    ('Ghana', 'Accra', 'Africa', 'easy'),
    ('Ethiopia', 'Addis Ababa', 'Africa', 'medium'),
    ('Senegal', 'Dakar', 'Africa', 'medium'),
    ('Algeria', 'Algiers', 'Africa', 'medium'),
    ('Tunisia', 'Tunis', 'Africa', 'medium'),
    ('Tanzania', 'Dodoma', 'Africa', 'hard'),
    ('Uganda', 'Kampala', 'Africa', 'medium'),
    ('Cameroon', 'Yaoundé', 'Africa', 'hard'),
    ('Madagascar', 'Antananarivo', 'Africa', 'hard'),
    ('Rwanda', 'Kigali', 'Africa', 'medium'),
    ('Zimbabwe', 'Harare', 'Africa', 'medium'),
    ('Mozambique', 'Maputo', 'Africa', 'hard'),
    ('Sudan', 'Khartoum', 'Africa', 'medium'),
    ('Botswana', 'Gaborone', 'Africa', 'hard'),
    ('Namibia', 'Windhoek', 'Africa', 'hard'),
    ('Zambia', 'Lusaka', 'Africa', 'hard'),
    ('Mali', 'Bamako', 'Africa', 'hard'),
    ('Libya', 'Tripoli', 'Africa', 'medium'),

    # Europe
    ('France', 'Paris', 'Europe', 'easy'),
    ('Germany', 'Berlin', 'Europe', 'easy'),
    ('Italy', 'Rome', 'Europe', 'easy'),
    ('Spain', 'Madrid', 'Europe', 'easy'),
    ('United Kingdom', 'London', 'Europe', 'easy'),
    ('Portugal', 'Lisbon', 'Europe', 'easy'),
    ('Netherlands', 'Amsterdam', 'Europe', 'easy'),
    ('Belgium', 'Brussels', 'Europe', 'easy'),
    ('Switzerland', 'Bern', 'Europe', 'medium'),
    ('Sweden', 'Stockholm', 'Europe', 'easy'),
    ('Norway', 'Oslo', 'Europe', 'easy'),
    ('Denmark', 'Copenhagen', 'Europe', 'easy'),
    ('Finland', 'Helsinki', 'Europe', 'medium'),
    ('Poland', 'Warsaw', 'Europe', 'medium'),
    ('Austria', 'Vienna', 'Europe', 'medium'),
    ('Greece', 'Athens', 'Europe', 'easy'),
    ('Ireland', 'Dublin', 'Europe', 'easy'),
    ('Hungary', 'Budapest', 'Europe', 'medium'),
    ('Czech Republic', 'Prague', 'Europe', 'medium'),
    ('Romania', 'Bucharest', 'Europe', 'medium'),
    ('Croatia', 'Zagreb', 'Europe', 'hard'),
    ('Iceland', 'Reykjavik', 'Europe', 'medium'),
    ('Russia', 'Moscow', 'Europe', 'easy'),
    ('Ukraine', 'Kyiv', 'Europe', 'easy'),
    ('Bulgaria', 'Sofia', 'Europe', 'medium'),
    ('Serbia', 'Belgrade', 'Europe', 'medium'),
    ('Slovakia', 'Bratislava', 'Europe', 'hard'),
    ('Slovenia', 'Ljubljana', 'Europe', 'hard'),
    ('Lithuania', 'Vilnius', 'Europe', 'hard'),
    ('Latvia', 'Riga', 'Europe', 'hard'),
    ('Estonia', 'Tallinn', 'Europe', 'hard'),

    # Asia
    ('Japan', 'Tokyo', 'Asia', 'easy'),
    ('China', 'Beijing', 'Asia', 'easy'),
    ('India', 'New Delhi', 'Asia', 'easy'),
    ('South Korea', 'Seoul', 'Asia', 'easy'),
    ('Indonesia', 'Jakarta', 'Asia', 'medium'),
    ('Thailand', 'Bangkok', 'Asia', 'easy'),
    ('Vietnam', 'Hanoi', 'Asia', 'medium'),
    ('Singapore', 'Singapore', 'Asia', 'easy'),
    ('Malaysia', 'Kuala Lumpur', 'Asia', 'medium'),
    ('Philippines', 'Manila', 'Asia', 'medium'),
    ('Pakistan', 'Islamabad', 'Asia', 'medium'),
    ('Bangladesh', 'Dhaka', 'Asia', 'medium'),
    ('Saudi Arabia', 'Riyadh', 'Asia', 'medium'),
    ('United Arab Emirates', 'Abu Dhabi', 'Asia', 'medium'),
    ('Iran', 'Tehran', 'Asia', 'medium'),
    ('Iraq', 'Baghdad', 'Asia', 'medium'),
    ('Turkey', 'Ankara', 'Asia', 'medium'),
    ('Israel', 'Jerusalem', 'Asia', 'medium'),
    ('Nepal', 'Kathmandu', 'Asia', 'hard'),
    ('Sri Lanka', 'Colombo', 'Asia', 'hard'),
    ('Mongolia', 'Ulaanbaatar', 'Asia', 'hard'),
    ('Kazakhstan', 'Astana', 'Asia', 'hard'),

    # North America
    ('United States', 'Washington', 'North America', 'easy'),
    ('Canada', 'Ottawa', 'North America', 'easy'),
    ('Mexico', 'Mexico City', 'North America', 'easy'),
    ('Cuba', 'Havana', 'North America', 'medium'),
    ('Jamaica', 'Kingston', 'North America', 'medium'),
    ('Guatemala', 'Guatemala City', 'North America', 'hard'),
    ('Panama', 'Panama City', 'North America', 'medium'),
    ('Costa Rica', 'San José', 'North America', 'medium'),

    # South America
    ('Brazil', 'Brasilia', 'South America', 'medium'),
    ('Argentina', 'Buenos Aires', 'South America', 'easy'),
    ('Chile', 'Santiago', 'South America', 'easy'),
    ('Peru', 'Lima', 'South America', 'easy'),
    ('Colombia', 'Bogotá', 'South America', 'medium'),
    ('Venezuela', 'Caracas', 'South America', 'medium'),
    ('Ecuador', 'Quito', 'South America', 'medium'),
    ('Bolivia', 'La Paz', 'South America', 'hard'),
    ('Uruguay', 'Montevideo', 'South America', 'medium'),
    ('Paraguay', 'Asunción', 'South America', 'hard'),

    # Oceania
    ('Australia', 'Canberra', 'Oceania', 'medium'),
    ('New Zealand', 'Wellington', 'Oceania', 'medium'),
    ('Fiji', 'Suva', 'Oceania', 'hard'),
    ('Papua New Guinea', 'Port Moresby', 'Oceania', 'hard'),
]

CONTINENTS = ['Africa', 'Europe', 'Asia',
              'North America', 'South America', 'Oceania', 'Antarctica']

# ============================================================
# LANDMARKS — (name, country, image_url, difficulty)
# Using Wikipedia Commons direct file URLs at reasonable sizes.
# Each one has been spot-checked for hotlink-friendly delivery.
# ============================================================

LANDMARKS = [
    ('Eiffel Tower', 'France',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Tour_Eiffel_Wikimedia_Commons.jpg?width=400', 'easy'),
    ('Statue of Liberty', 'United States',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Statue_of_Liberty_7.jpg?width=400', 'easy'),
    ('Big Ben', 'United Kingdom',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Elizabeth_Tower,_June_2022.jpg?width=400', 'easy'),
    ('Colosseum', 'Italy',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Colosseo_2020.jpg?width=400', 'easy'),
    ('Taj Mahal', 'India',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Taj_Mahal_(Edited).jpeg?width=400', 'easy'),
    ('Great Pyramid of Giza', 'Egypt',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Kheops-Pyramid.jpg?width=400', 'easy'),
    ('Sydney Opera House', 'Australia',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Sydney_Opera_House_-_Dec_2008.jpg?width=400', 'easy'),
    ('Christ the Redeemer', 'Brazil',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Christ_on_Corcovado_mountain.JPG?width=400', 'easy'),
    ('Machu Picchu', 'Peru',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Machu_Picchu,_Peru.jpg?width=400', 'easy'),
    ('Great Wall of China', 'China',
     'https://commons.wikimedia.org/wiki/Special:FilePath/The_Great_Wall_of_China_at_Jinshanling-edit.jpg?width=400', 'easy'),
    ('Mona Lisa', 'France',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg?width=300', 'medium'),
    ('Petra', 'Jordan',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Treasury_petra_crop.jpeg?width=400', 'medium'),
    ('Stonehenge', 'United Kingdom',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Stonehenge2007_07_30.jpg?width=400', 'easy'),
    ('Mount Fuji', 'Japan',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Kawaguchiko_Sakura_Mount_Fuji_2.jpg?width=400', 'easy'),
    ('Burj Khalifa', 'United Arab Emirates',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Burj_Khalifa.jpg?width=300', 'medium'),
    ('Acropolis of Athens', 'Greece',
     'https://commons.wikimedia.org/wiki/Special:FilePath/The_Acropolis_of_Athens_seen_from_the_Hill_of_the_Muses.jpg?width=400', 'medium'),
    ('Angkor Wat', 'Cambodia',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Angkor_Wat_temple.jpg?width=400', 'medium'),
    ('Niagara Falls', 'Canada',
     'https://commons.wikimedia.org/wiki/Special:FilePath/3Falls_Niagara.jpg?width=400', 'easy'),
    ('Brandenburg Gate', 'Germany',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Brandenburger_Tor_abends.jpg?width=400', 'medium'),
    ('Chichen Itza', 'Mexico',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Chichen_Itza_3.jpg?width=400', 'medium'),
    ('Sagrada Familia', 'Spain',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Sagrada_Familia_8-12-21_(3).jpg?width=300', 'medium'),
    ('Table Mountain', 'South Africa',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Table_Mountain_DanieVDM.jpg?width=400', 'hard'),
    ('Hagia Sophia', 'Turkey',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Aya_sofya.jpg?width=400', 'medium'),
    ('Mount Rushmore', 'United States',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Dean_Franklin_-_06.04.03_Mount_Rushmore_Monument_(by-sa)-3_new.jpg?width=400', 'easy'),
    ('Forbidden City', 'China',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Forbidden_City_Beijing_Shenwumen_Gate.jpg?width=400', 'medium'),
    ('Leaning Tower of Pisa', 'Italy',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Pisa_-_Campanile_-_2024-04-18.jpg?width=300', 'easy'),
    ('Moai (Easter Island)', 'Chile',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Moai_Rano_raraku.jpg?width=400', 'medium'),
    ('Kremlin', 'Russia',
     'https://commons.wikimedia.org/wiki/Special:FilePath/Moscow_Kremlin_from_Kamenny_bridge.jpg?width=400', 'medium'),
]


def filter_by_difficulty(pool, difficulty: str):
    if difficulty == 'mixed' or not difficulty:
        return list(pool)
    return [p for p in pool if (p[-1] == difficulty)]


def get_flags_round(n: int, difficulty: str = 'mixed'):
    pool = filter_by_difficulty(FLAGS, difficulty)
    if not pool: pool = list(FLAGS)
    import random
    sample = random.sample(pool, min(n, len(pool)))
    return [{'country': c, 'image': u, 'difficulty': d} for (c, u, d) in sample]


def get_capitals_round(n: int, difficulty: str = 'mixed'):
    pool = filter_by_difficulty(COUNTRIES_DATA, difficulty)
    if not pool: pool = list(COUNTRIES_DATA)
    import random
    sample = random.sample(pool, min(n, len(pool)))
    out = []
    all_capitals = [d[1] for d in COUNTRIES_DATA]
    for (country, capital, continent, diff) in sample:
        wrong = [c for c in all_capitals if c != capital]
        opts = random.sample(wrong, 3) + [capital]
        random.shuffle(opts)
        out.append({
            'country': country, 'answer': capital, 'options': opts,
            'continent': continent, 'difficulty': diff
        })
    return out


def get_continents_round(n: int, difficulty: str = 'mixed'):
    pool = filter_by_difficulty(COUNTRIES_DATA, difficulty)
    if not pool: pool = list(COUNTRIES_DATA)
    import random
    sample = random.sample(pool, min(n, len(pool)))
    opts = ['Africa', 'Europe', 'Asia', 'North America', 'South America', 'Oceania']
    out = []
    for (country, capital, continent, diff) in sample:
        these_opts = list(opts)
        random.shuffle(these_opts)
        out.append({
            'country': country, 'answer': continent, 'options': these_opts,
            'difficulty': diff
        })
    return out


def get_landmarks_round(n: int, difficulty: str = 'mixed'):
    pool = filter_by_difficulty(LANDMARKS, difficulty)
    if not pool: pool = list(LANDMARKS)
    import random
    sample = random.sample(pool, min(n, len(pool)))
    return [{'name': name, 'country': country, 'image': url, 'difficulty': diff}
            for (name, country, url, diff) in sample]
