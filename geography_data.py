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
    ('Soviet Union',         'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Flag_of_the_Soviet_Union.svg/330px-Flag_of_the_Soviet_Union.svg.png', 'legend'),
    ('East Germany',         'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Flag_of_East_Germany.svg/330px-Flag_of_East_Germany.svg.png', 'legend'),
    ('Yugoslavia',           'https://upload.wikimedia.org/wikipedia/commons/thumb/6/61/Flag_of_Yugoslavia_%281946-1992%29.svg/330px-Flag_of_Yugoslavia_%281946-1992%29.svg.png', 'legend'),
    ('Czechoslovakia',       'https://upload.wikimedia.org/wikipedia/commons/thumb/c/cb/Flag_of_the_Czech_Republic.svg/330px-Flag_of_the_Czech_Republic.svg.png', 'legend'),
    ('Ottoman Empire',       'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/Flag_of_the_Ottoman_Empire_%281844%E2%80%931922%29.svg/330px-Flag_of_the_Ottoman_Empire_%281844%E2%80%931922%29.svg.png', 'legend'),
    ('Austria-Hungary',      'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Ensign_of_Austro-Hungarian_civil_fleet_%281869-1918%29.svg/330px-Ensign_of_Austro-Hungarian_civil_fleet_%281869-1918%29.svg.png', 'legend'),
    ('Persian Empire',       'https://upload.wikimedia.org/wikipedia/commons/thumb/e/ed/Civil_flag_of_Iran_%281933%E2%80%931964%29.svg/330px-Civil_flag_of_Iran_%281933%E2%80%931964%29.svg.png', 'legend'),
    ('Republic of Texas',    'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f7/Flag_of_Texas.svg/330px-Flag_of_Texas.svg.png', 'legend'),
    ('Confederate States',   'https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Flag_of_the_Confederate_States_%281865%29.svg/330px-Flag_of_the_Confederate_States_%281865%29.svg.png', 'legend'),
    ('Kingdom of Hawaii',    'https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Flag_of_Hawaii.svg/330px-Flag_of_Hawaii.svg.png', 'legend'),
    ('Tibet',                'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Flag_of_Tibet.svg/330px-Flag_of_Tibet.svg.png', 'legend'),
    ('Catalonia',            'https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/Flag_of_Catalonia.svg/330px-Flag_of_Catalonia.svg.png', 'legend'),
    ('Scotland',             'https://upload.wikimedia.org/wikipedia/commons/thumb/1/10/Flag_of_Scotland.svg/330px-Flag_of_Scotland.svg.png', 'legend'),
    ('Wales',                'https://upload.wikimedia.org/wikipedia/commons/thumb/d/dc/Flag_of_Wales.svg/330px-Flag_of_Wales.svg.png', 'legend'),
    ('Basque Country',       'https://upload.wikimedia.org/wikipedia/commons/thumb/2/2d/Flag_of_the_Basque_Country.svg/330px-Flag_of_the_Basque_Country.svg.png', 'legend'),
    ('Taiwan',               'https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Flag_of_the_Republic_of_China.svg/330px-Flag_of_the_Republic_of_China.svg.png', 'legend'),
    ('Hong Kong',            'https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Flag_of_Hong_Kong.svg/330px-Flag_of_Hong_Kong.svg.png', 'legend'),
    ('Palestine',            'https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Flag_of_Palestine.svg/330px-Flag_of_Palestine.svg.png', 'legend'),
    ('Greenland',            'https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/Flag_of_Greenland.svg/330px-Flag_of_Greenland.svg.png', 'legend'),
    ('Faroe Islands',        'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Flag_of_the_Faroe_Islands.svg/330px-Flag_of_the_Faroe_Islands.svg.png', 'legend'),
    ('Puerto Rico',          'https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/Flag_of_Puerto_Rico.svg/330px-Flag_of_Puerto_Rico.svg.png', 'legend'),
    ('Bermuda',              'https://upload.wikimedia.org/wikipedia/commons/thumb/b/bf/Flag_of_Bermuda.svg/330px-Flag_of_Bermuda.svg.png', 'legend'),
    ('Anguilla',             'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Flag_of_Anguilla.svg/330px-Flag_of_Anguilla.svg.png', 'legend'),
    ('Cook Islands',         'https://upload.wikimedia.org/wikipedia/commons/thumb/3/35/Flag_of_the_Cook_Islands.svg/330px-Flag_of_the_Cook_Islands.svg.png', 'legend'),
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
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg/500px-Tour_Eiffel_Wikimedia_Commons.jpg', 'easy'),
    ('Statue of Liberty', 'United States',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Statue_of_Liberty_7.jpg/500px-Statue_of_Liberty_7.jpg', 'easy'),
    ('Big Ben', 'United Kingdom',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/4/43/Elizabeth_Tower%2C_June_2022.jpg/500px-Elizabeth_Tower%2C_June_2022.jpg', 'easy'),
    ('Colosseum', 'Italy',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Colosseo_2020.jpg/500px-Colosseo_2020.jpg', 'easy'),
    ('Taj Mahal', 'India',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/1/1d/Taj_Mahal_%28Edited%29.jpeg/500px-Taj_Mahal_%28Edited%29.jpeg', 'easy'),
    ('Great Pyramid of Giza', 'Egypt',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Kheops-Pyramid.jpg/500px-Kheops-Pyramid.jpg', 'easy'),
    ('Sydney Opera House', 'Australia',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/7/7c/Sydney_Opera_House_-_Dec_2008.jpg/500px-Sydney_Opera_House_-_Dec_2008.jpg', 'easy'),
    ('Christ the Redeemer', 'Brazil',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/Christ_on_Corcovado_mountain.JPG/500px-Christ_on_Corcovado_mountain.JPG', 'easy'),
    ('Machu Picchu', 'Peru',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/e/eb/Machu_Picchu%2C_Peru.jpg/500px-Machu_Picchu%2C_Peru.jpg', 'easy'),
    ('Great Wall of China', 'China',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/The_Great_Wall_of_China_at_Jinshanling-edit.jpg/500px-The_Great_Wall_of_China_at_Jinshanling-edit.jpg', 'easy'),
    ('Mona Lisa', 'France',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg/500px-Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg', 'medium'),
    ('Petra', 'Jordan',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Treasury_petra_crop.jpeg/500px-Treasury_petra_crop.jpeg', 'medium'),
    ('Stonehenge', 'United Kingdom',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Stonehenge2007_07_30.jpg/500px-Stonehenge2007_07_30.jpg', 'easy'),
    ('Mount Fuji', 'Japan',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f6/Mount_Fuji_from_Hotel_Mt_Fuji_1995-2-7.jpg/500px-Mount_Fuji_from_Hotel_Mt_Fuji_1995-2-7.jpg', 'easy'),
    ('Burj Khalifa', 'United Arab Emirates',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/9/90/Burj_Khalifa_%28worlds_tallest_building%29_and_the_Dubai_skyline_%2825781049892%29.jpg/500px-Burj_Khalifa_%28worlds_tallest_building%29_and_the_Dubai_skyline_%2825781049892%29.jpg', 'medium'),
    ('Acropolis of Athens', 'Greece',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/2/2c/1029_Acropolis_of_Athens_in_Greece_at_night_Photo_by_Giles_Laurent.jpg/500px-1029_Acropolis_of_Athens_in_Greece_at_night_Photo_by_Giles_Laurent.jpg', 'medium'),
    ('Angkor Wat', 'Cambodia',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/4/41/Angkor_Wat.jpg/500px-Angkor_Wat.jpg', 'medium'),
    ('Niagara Falls', 'Canada',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/3Falls_Niagara.jpg/500px-3Falls_Niagara.jpg', 'easy'),
    ('Brandenburg Gate', 'Germany',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a6/Brandenburger_Tor_abends.jpg/500px-Brandenburger_Tor_abends.jpg', 'medium'),
    ('Chichen Itza', 'Mexico',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/5/51/Chichen_Itza_3.jpg/500px-Chichen_Itza_3.jpg', 'medium'),
    ('Sagrada Familia', 'Spain',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/e/ee/Sagrada_Familia_01.jpg/500px-Sagrada_Familia_01.jpg', 'medium'),
    ('Table Mountain', 'South Africa',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/d/dc/Table_Mountain_DanieVDM.jpg/500px-Table_Mountain_DanieVDM.jpg', 'hard'),
    ('Hagia Sophia', 'Turkey',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4a/Aya_sofya.jpg/500px-Aya_sofya.jpg', 'medium'),
    ('Mount Rushmore', 'United States',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Dean_Franklin_-_06.04.03_Mount_Rushmore_Monument_%28by-sa%29-3_new.jpg/500px-Dean_Franklin_-_06.04.03_Mount_Rushmore_Monument_%28by-sa%29-3_new.jpg', 'easy'),
    ('Forbidden City', 'China',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/The_Forbidden_City_-_View_from_Coal_Hill.jpg/500px-The_Forbidden_City_-_View_from_Coal_Hill.jpg', 'medium'),
    ('Leaning Tower of Pisa', 'Italy',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/6/66/The_Leaning_Tower_of_Pisa_SB.jpeg/500px-The_Leaning_Tower_of_Pisa_SB.jpeg', 'easy'),
    ('Moai (Easter Island)', 'Chile',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Moai_Rano_raraku.jpg/500px-Moai_Rano_raraku.jpg', 'medium'),
    ('Kremlin', 'Russia',
     'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a6/Moscow_Kremlin_from_Kamenny_bridge.jpg/500px-Moscow_Kremlin_from_Kamenny_bridge.jpg', 'medium'),
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


# --- Admin content integration ---
_BUILTIN_FLAGS_DATA_COUNT = len(FLAGS_DATA)
_BUILTIN_LANDMARKS_COUNT = len(LANDMARKS)


def _build_flag_url(name, iso_or_url, diff):
    """Build a (name, image_url, diff) flag entry. Admin flags may pass a
    direct URL via the 'url:' prefix in the iso slot."""
    if iso_or_url.startswith('url:'):
        return (name, iso_or_url[4:], diff)
    return (name, f'https://flagcdn.com/w320/{iso_or_url.lower()}.png', diff)


def refresh_admin_content():
    """Re-sync FLAGS and LANDMARKS = builtin + current admin items."""
    global FLAGS, LANDMARKS
    try:
        import admin_content
        # Flags: builtin flagcdn flags + legend flags + admin flags
        flags_data = admin_content.merged_geo_flags(FLAGS_DATA[:_BUILTIN_FLAGS_DATA_COUNT])
        new_flags = []
        for (name, iso, diff) in flags_data:
            new_flags.append(_build_flag_url(name, iso, diff))
        for entry in LEGEND_FLAGS_DATA:
            new_flags.append(entry)
        FLAGS = new_flags
        # Landmarks: builtin + admin
        LANDMARKS = admin_content.merged_geo_landmarks(LANDMARKS[:_BUILTIN_LANDMARKS_COUNT])
    except Exception as e:
        print(f"[geography] refresh_admin_content failed: {e}")
