"""
FootyMind player pool.

Each entry: dict with:
  - name: canonical display name
  - aliases: lowercase strings that should all resolve to this player
  - nationality: country (used as a hint)
  - position: rough position (used as a hint)
  - difficulty: easy | medium | hard
  - path: list of (years, club) tuples in chronological order
  - last_club_revealed: which path step to reveal first (default last_club_revealed=False)

Difficulty bands:
  EASY   -> household names anyone with passing football interest knows
  MEDIUM -> well-known players but more specific (fans recognize, casuals might miss)
  HARD   -> deeper cuts, era-spanning legends, less mainstream picks

Each player has multiple aliases. Matching is case-insensitive, accent-stripped,
punctuation-stripped, and trims common honorifics.
"""

PLAYERS = [
    # ============================================================
    # EASY — household names
    # ============================================================
    {
        'name': 'Lionel Messi',
        'aliases': ['messi', 'lionel messi', 'leo messi', 'l messi', 'la pulga'],
        'nationality': 'Argentina',
        'position': 'Forward',
        'difficulty': 'easy',
        'path': [
            ('2004-2021', 'Barcelona'),
            ('2021-2023', 'Paris Saint-Germain'),
            ('2023-now',  'Inter Miami')
        ]
    },
    {
        'name': 'Cristiano Ronaldo',
        'aliases': ['ronaldo', 'cristiano', 'cristiano ronaldo', 'cr7', 'cr', 'c ronaldo'],
        'nationality': 'Portugal',
        'position': 'Forward',
        'difficulty': 'easy',
        'path': [
            ('2002-2003', 'Sporting CP'),
            ('2003-2009', 'Manchester United'),
            ('2009-2018', 'Real Madrid'),
            ('2018-2021', 'Juventus'),
            ('2021-2022', 'Manchester United'),
            ('2023-now',  'Al-Nassr')
        ]
    },
    {
        'name': 'Neymar',
        'aliases': ['neymar', 'neymar jr', 'neymar junior', 'ney'],
        'nationality': 'Brazil',
        'position': 'Forward',
        'difficulty': 'easy',
        'path': [
            ('2009-2013', 'Santos'),
            ('2013-2017', 'Barcelona'),
            ('2017-2023', 'Paris Saint-Germain'),
            ('2023-now',  'Al-Hilal')
        ]
    },
    {
        'name': 'Kylian Mbappé',
        'aliases': ['mbappe', 'kylian mbappe', 'kylian', 'k mbappe', 'mbappé'],
        'nationality': 'France',
        'position': 'Forward',
        'difficulty': 'easy',
        'path': [
            ('2015-2017', 'Monaco'),
            ('2017-2024', 'Paris Saint-Germain'),
            ('2024-now',  'Real Madrid')
        ]
    },
    {
        'name': 'Erling Haaland',
        'aliases': ['haaland', 'erling haaland', 'erling', 'haland'],
        'nationality': 'Norway',
        'position': 'Striker',
        'difficulty': 'easy',
        'path': [
            ('2017-2018', 'Bryne'),
            ('2018-2019', 'Molde'),
            ('2019-2020', 'Red Bull Salzburg'),
            ('2020-2022', 'Borussia Dortmund'),
            ('2022-now',  'Manchester City')
        ]
    },
    {
        'name': 'Mohamed Salah',
        'aliases': ['salah', 'mo salah', 'mohamed salah', 'mohammed salah', 'mosalah'],
        'nationality': 'Egypt',
        'position': 'Winger',
        'difficulty': 'easy',
        'path': [
            ('2010-2012', 'Al Mokawloon'),
            ('2012-2014', 'Basel'),
            ('2014-2016', 'Chelsea'),
            ('2015-2016', 'Fiorentina (loan)'),
            ('2016-2017', 'Roma'),
            ('2017-now',  'Liverpool')
        ]
    },
    {
        'name': 'Harry Kane',
        'aliases': ['kane', 'harry kane', 'h kane'],
        'nationality': 'England',
        'position': 'Striker',
        'difficulty': 'easy',
        'path': [
            ('2009-2023', 'Tottenham'),
            ('2023-now',  'Bayern Munich')
        ]
    },
    {
        'name': 'Kevin De Bruyne',
        'aliases': ['de bruyne', 'kevin de bruyne', 'kdb', 'k de bruyne', 'debruyne'],
        'nationality': 'Belgium',
        'position': 'Midfielder',
        'difficulty': 'easy',
        'path': [
            ('2008-2012', 'Genk'),
            ('2012-2014', 'Chelsea'),
            ('2014-2015', 'Wolfsburg'),
            ('2015-now',  'Manchester City')
        ]
    },
    {
        'name': 'Robert Lewandowski',
        'aliases': ['lewandowski', 'robert lewandowski', 'lewy', 'r lewandowski'],
        'nationality': 'Poland',
        'position': 'Striker',
        'difficulty': 'easy',
        'path': [
            ('2008-2010', 'Lech Poznań'),
            ('2010-2014', 'Borussia Dortmund'),
            ('2014-2022', 'Bayern Munich'),
            ('2022-now',  'Barcelona')
        ]
    },
    {
        'name': 'Karim Benzema',
        'aliases': ['benzema', 'karim benzema', 'k benzema'],
        'nationality': 'France',
        'position': 'Striker',
        'difficulty': 'easy',
        'path': [
            ('2005-2009', 'Lyon'),
            ('2009-2023', 'Real Madrid'),
            ('2023-now',  'Al-Ittihad')
        ]
    },
    {
        'name': 'Luka Modrić',
        'aliases': ['modric', 'luka modric', 'modrić', 'luka modrić'],
        'nationality': 'Croatia',
        'position': 'Midfielder',
        'difficulty': 'easy',
        'path': [
            ('2003-2008', 'Dinamo Zagreb'),
            ('2008-2012', 'Tottenham'),
            ('2012-now',  'Real Madrid')
        ]
    },
    {
        'name': 'Vinícius Júnior',
        'aliases': ['vinicius', 'vini', 'vinicius junior', 'vini jr', 'vinícius', 'vinicius jr'],
        'nationality': 'Brazil',
        'position': 'Winger',
        'difficulty': 'easy',
        'path': [
            ('2017-2018', 'Flamengo'),
            ('2018-now',  'Real Madrid')
        ]
    },
    {
        'name': 'Jude Bellingham',
        'aliases': ['bellingham', 'jude bellingham', 'jude', 'j bellingham'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'easy',
        'path': [
            ('2019-2020', 'Birmingham City'),
            ('2020-2023', 'Borussia Dortmund'),
            ('2023-now',  'Real Madrid')
        ]
    },
    {
        'name': 'Bukayo Saka',
        'aliases': ['saka', 'bukayo saka', 'b saka'],
        'nationality': 'England',
        'position': 'Winger',
        'difficulty': 'easy',
        'path': [
            ('2018-now', 'Arsenal')
        ]
    },
    {
        'name': 'Virgil van Dijk',
        'aliases': ['van dijk', 'virgil van dijk', 'vvd', 'v van dijk', 'virgil'],
        'nationality': 'Netherlands',
        'position': 'Defender',
        'difficulty': 'easy',
        'path': [
            ('2011-2013', 'Groningen'),
            ('2013-2015', 'Celtic'),
            ('2015-2018', 'Southampton'),
            ('2018-now',  'Liverpool')
        ]
    },
    {
        'name': 'Sadio Mané',
        'aliases': ['mane', 'sadio mane', 'mané', 'sadio mané'],
        'nationality': 'Senegal',
        'position': 'Winger',
        'difficulty': 'easy',
        'path': [
            ('2011-2012', 'Metz'),
            ('2012-2014', 'Red Bull Salzburg'),
            ('2014-2016', 'Southampton'),
            ('2016-2022', 'Liverpool'),
            ('2022-2023', 'Bayern Munich'),
            ('2023-now',  'Al-Nassr')
        ]
    },
    {
        'name': 'Son Heung-min',
        'aliases': ['son', 'son heung min', 'son heung-min', 'sonny', 'heung min son', 'h m son'],
        'nationality': 'South Korea',
        'position': 'Forward',
        'difficulty': 'easy',
        'path': [
            ('2010-2013', 'Hamburg'),
            ('2013-2015', 'Bayer Leverkusen'),
            ('2015-now',  'Tottenham')
        ]
    },
    {
        'name': 'Pedri',
        'aliases': ['pedri', 'pedri gonzalez', 'pedri gonzález'],
        'nationality': 'Spain',
        'position': 'Midfielder',
        'difficulty': 'easy',
        'path': [
            ('2019-2020', 'Las Palmas'),
            ('2020-now',  'Barcelona')
        ]
    },

    # ============================================================
    # MEDIUM — known to fans, less to casuals
    # ============================================================
    {
        'name': 'Antoine Griezmann',
        'aliases': ['griezmann', 'antoine griezmann', 'grizou', 'a griezmann'],
        'nationality': 'France',
        'position': 'Forward',
        'difficulty': 'medium',
        'path': [
            ('2009-2014', 'Real Sociedad'),
            ('2014-2019', 'Atlético Madrid'),
            ('2019-2021', 'Barcelona'),
            ('2021-now',  'Atlético Madrid')
        ]
    },
    {
        'name': 'Bruno Fernandes',
        'aliases': ['bruno fernandes', 'bruno', 'b fernandes', 'fernandes'],
        'nationality': 'Portugal',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2012-2013', 'Novara'),
            ('2013-2016', 'Udinese'),
            ('2016-2017', 'Sampdoria'),
            ('2017-2020', 'Sporting CP'),
            ('2020-now',  'Manchester United')
        ]
    },
    {
        'name': 'Sergio Ramos',
        'aliases': ['ramos', 'sergio ramos', 's ramos'],
        'nationality': 'Spain',
        'position': 'Defender',
        'difficulty': 'medium',
        'path': [
            ('2004-2005', 'Sevilla'),
            ('2005-2021', 'Real Madrid'),
            ('2021-2023', 'Paris Saint-Germain'),
            ('2023-now',  'Sevilla')
        ]
    },
    {
        'name': 'Toni Kroos',
        'aliases': ['kroos', 'toni kroos', 't kroos'],
        'nationality': 'Germany',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2007-2014', 'Bayern Munich'),
            ('2009-2010', 'Bayer Leverkusen (loan)'),
            ('2014-2024', 'Real Madrid')
        ]
    },
    {
        'name': 'Thibaut Courtois',
        'aliases': ['courtois', 'thibaut courtois', 't courtois'],
        'nationality': 'Belgium',
        'position': 'Goalkeeper',
        'difficulty': 'medium',
        'path': [
            ('2009-2011', 'Genk'),
            ('2011-2014', 'Chelsea'),
            ('2011-2014', 'Atlético Madrid (loan)'),
            ('2014-2018', 'Chelsea'),
            ('2018-now',  'Real Madrid')
        ]
    },
    {
        'name': 'Marcus Rashford',
        'aliases': ['rashford', 'marcus rashford', 'm rashford'],
        'nationality': 'England',
        'position': 'Forward',
        'difficulty': 'medium',
        'path': [
            ('2014-2024', 'Manchester United'),
            ('2025-now',  'Aston Villa')
        ]
    },
    {
        'name': 'Phil Foden',
        'aliases': ['foden', 'phil foden', 'p foden'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2017-now', 'Manchester City')
        ]
    },
    {
        'name': 'Rodri',
        'aliases': ['rodri', 'rodrigo hernandez', 'rodrigo'],
        'nationality': 'Spain',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2015-2018', 'Villarreal'),
            ('2018-2019', 'Atlético Madrid'),
            ('2019-now',  'Manchester City')
        ]
    },
    {
        'name': 'Joshua Kimmich',
        'aliases': ['kimmich', 'joshua kimmich', 'j kimmich'],
        'nationality': 'Germany',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2013-2015', 'RB Leipzig'),
            ('2015-now',  'Bayern Munich')
        ]
    },
    {
        'name': 'Florian Wirtz',
        'aliases': ['wirtz', 'florian wirtz', 'f wirtz'],
        'nationality': 'Germany',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2020-2025', 'Bayer Leverkusen'),
            ('2025-now',  'Liverpool')
        ]
    },
    {
        'name': 'Lautaro Martínez',
        'aliases': ['lautaro', 'lautaro martinez', 'martinez', 'l martinez', 'el toro'],
        'nationality': 'Argentina',
        'position': 'Striker',
        'difficulty': 'medium',
        'path': [
            ('2015-2018', 'Racing Club'),
            ('2018-now',  'Inter Milan')
        ]
    },
    {
        'name': 'Victor Osimhen',
        'aliases': ['osimhen', 'victor osimhen', 'v osimhen'],
        'nationality': 'Nigeria',
        'position': 'Striker',
        'difficulty': 'medium',
        'path': [
            ('2017-2018', 'Wolfsburg'),
            ('2018-2019', 'Charleroi (loan)'),
            ('2019-2020', 'Lille'),
            ('2020-2024', 'Napoli'),
            ('2024-now',  'Galatasaray')
        ]
    },
    {
        'name': 'Riyad Mahrez',
        'aliases': ['mahrez', 'riyad mahrez', 'r mahrez'],
        'nationality': 'Algeria',
        'position': 'Winger',
        'difficulty': 'medium',
        'path': [
            ('2009-2014', 'Le Havre'),
            ('2014-2018', 'Leicester City'),
            ('2018-2023', 'Manchester City'),
            ('2023-now',  'Al-Ahli')
        ]
    },
    {
        'name': 'N\'Golo Kanté',
        'aliases': ['kante', 'ngolo kante', "n'golo kante", 'n golo kante', "n'golo kanté"],
        'nationality': 'France',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2012-2013', 'Boulogne'),
            ('2013-2015', 'Caen'),
            ('2015-2016', 'Leicester City'),
            ('2016-2023', 'Chelsea'),
            ('2023-now',  'Al-Ittihad')
        ]
    },
    {
        'name': 'Manuel Neuer',
        'aliases': ['neuer', 'manuel neuer', 'm neuer'],
        'nationality': 'Germany',
        'position': 'Goalkeeper',
        'difficulty': 'medium',
        'path': [
            ('2006-2011', 'Schalke 04'),
            ('2011-now',  'Bayern Munich')
        ]
    },
    {
        'name': 'Alisson Becker',
        'aliases': ['alisson', 'alisson becker', 'allison'],
        'nationality': 'Brazil',
        'position': 'Goalkeeper',
        'difficulty': 'medium',
        'path': [
            ('2013-2016', 'Internacional'),
            ('2016-2018', 'Roma'),
            ('2018-now',  'Liverpool')
        ]
    },
    {
        'name': 'Trent Alexander-Arnold',
        'aliases': ['trent', 'alexander arnold', 'trent alexander-arnold', 'taa', 't alexander-arnold'],
        'nationality': 'England',
        'position': 'Defender',
        'difficulty': 'medium',
        'path': [
            ('2016-2025', 'Liverpool'),
            ('2025-now',  'Real Madrid')
        ]
    },
    {
        'name': 'Rúben Dias',
        'aliases': ['ruben dias', 'rúben dias', 'dias', 'r dias'],
        'nationality': 'Portugal',
        'position': 'Defender',
        'difficulty': 'medium',
        'path': [
            ('2017-2020', 'Benfica'),
            ('2020-now',  'Manchester City')
        ]
    },
    {
        'name': 'Jamal Musiala',
        'aliases': ['musiala', 'jamal musiala', 'j musiala'],
        'nationality': 'Germany',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2019-now', 'Bayern Munich')
        ]
    },
    {
        'name': 'Mason Mount',
        'aliases': ['mount', 'mason mount', 'm mount'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2017-2018', 'Vitesse (loan)'),
            ('2018-2019', 'Derby County (loan)'),
            ('2019-2023', 'Chelsea'),
            ('2023-now',  'Manchester United')
        ]
    },
    {
        'name': 'Declan Rice',
        'aliases': ['rice', 'declan rice', 'd rice'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2017-2023', 'West Ham'),
            ('2023-now',  'Arsenal')
        ]
    },
    {
        'name': 'Achraf Hakimi',
        'aliases': ['hakimi', 'achraf hakimi', 'a hakimi'],
        'nationality': 'Morocco',
        'position': 'Defender',
        'difficulty': 'medium',
        'path': [
            ('2017-2018', 'Real Madrid'),
            ('2018-2020', 'Borussia Dortmund (loan)'),
            ('2020-2021', 'Inter Milan'),
            ('2021-now',  'Paris Saint-Germain')
        ]
    },
    {
        'name': 'Ousmane Dembélé',
        'aliases': ['dembele', 'ousmane dembele', 'dembélé', 'o dembele'],
        'nationality': 'France',
        'position': 'Winger',
        'difficulty': 'medium',
        'path': [
            ('2014-2016', 'Rennes'),
            ('2016-2017', 'Borussia Dortmund'),
            ('2017-2023', 'Barcelona'),
            ('2023-now',  'Paris Saint-Germain')
        ]
    },
    {
        'name': 'João Félix',
        'aliases': ['joao felix', 'felix', 'joão félix', 'j felix'],
        'nationality': 'Portugal',
        'position': 'Forward',
        'difficulty': 'medium',
        'path': [
            ('2018-2019', 'Benfica'),
            ('2019-2024', 'Atlético Madrid'),
            ('2023-2024', 'Barcelona (loan)'),
            ('2024-2025', 'Chelsea'),
            ('2025-now',  'Milan')
        ]
    },
    {
        'name': 'Federico Valverde',
        'aliases': ['valverde', 'federico valverde', 'fede valverde', 'f valverde'],
        'nationality': 'Uruguay',
        'position': 'Midfielder',
        'difficulty': 'medium',
        'path': [
            ('2015-2016', 'Peñarol'),
            ('2016-now',  'Real Madrid'),
            ('2017-2018', 'Deportivo (loan)')
        ]
    },
    {
        'name': 'Cole Palmer',
        'aliases': ['palmer', 'cole palmer', 'c palmer'],
        'nationality': 'England',
        'position': 'Forward',
        'difficulty': 'medium',
        'path': [
            ('2020-2023', 'Manchester City'),
            ('2023-now',  'Chelsea')
        ]
    },
    {
        'name': 'Lamine Yamal',
        'aliases': ['yamal', 'lamine yamal', 'l yamal', 'lamine'],
        'nationality': 'Spain',
        'position': 'Winger',
        'difficulty': 'medium',
        'path': [
            ('2023-now', 'Barcelona')
        ]
    },

    # ============================================================
    # HARD — legends, era-spanners, deeper picks
    # ============================================================
    {
        'name': 'Zinedine Zidane',
        'aliases': ['zidane', 'zinedine zidane', 'zizou', 'zz'],
        'nationality': 'France',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('1989-1992', 'Cannes'),
            ('1992-1996', 'Bordeaux'),
            ('1996-2001', 'Juventus'),
            ('2001-2006', 'Real Madrid')
        ]
    },
    {
        'name': 'Ronaldinho',
        'aliases': ['ronaldinho', 'ronaldinho gaucho', 'dinho', 'ronaldinho gaúcho'],
        'nationality': 'Brazil',
        'position': 'Forward',
        'difficulty': 'hard',
        'path': [
            ('1998-2001', 'Grêmio'),
            ('2001-2003', 'Paris Saint-Germain'),
            ('2003-2008', 'Barcelona'),
            ('2008-2011', 'Milan'),
            ('2011-2012', 'Flamengo'),
            ('2012-2014', 'Atlético Mineiro')
        ]
    },
    {
        'name': 'Andrés Iniesta',
        'aliases': ['iniesta', 'andres iniesta', 'andrés iniesta', 'a iniesta'],
        'nationality': 'Spain',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('2002-2018', 'Barcelona'),
            ('2018-2023', 'Vissel Kobe'),
            ('2023-2024', 'Emirates Club')
        ]
    },
    {
        'name': 'Xavi Hernández',
        'aliases': ['xavi', 'xavi hernandez', 'xavi hernández'],
        'nationality': 'Spain',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('1998-2015', 'Barcelona'),
            ('2015-2019', 'Al Sadd')
        ]
    },
    {
        'name': 'Frank Lampard',
        'aliases': ['lampard', 'frank lampard', 'super frank', 'f lampard'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('1995-2001', 'West Ham'),
            ('2001-2014', 'Chelsea'),
            ('2014-2015', 'Manchester City'),
            ('2015-2016', 'New York City FC')
        ]
    },
    {
        'name': 'Steven Gerrard',
        'aliases': ['gerrard', 'steven gerrard', 'stevie g', 's gerrard'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('1998-2015', 'Liverpool'),
            ('2015-2016', 'LA Galaxy')
        ]
    },
    {
        'name': 'Thierry Henry',
        'aliases': ['henry', 'thierry henry', 'titi', 't henry'],
        'nationality': 'France',
        'position': 'Forward',
        'difficulty': 'hard',
        'path': [
            ('1994-1999', 'Monaco'),
            ('1999-2000', 'Juventus'),
            ('1999-2007', 'Arsenal'),
            ('2007-2010', 'Barcelona'),
            ('2010-2014', 'New York Red Bulls')
        ]
    },
    {
        'name': 'Ronaldo Nazário',
        'aliases': ['ronaldo nazario', 'r9', 'el fenomeno', 'ronaldo brazilian', 'brazilian ronaldo', 'ronaldo nazário'],
        'nationality': 'Brazil',
        'position': 'Striker',
        'difficulty': 'hard',
        'path': [
            ('1993-1994', 'Cruzeiro'),
            ('1994-1996', 'PSV'),
            ('1996-1997', 'Barcelona'),
            ('1997-2002', 'Inter Milan'),
            ('2002-2007', 'Real Madrid'),
            ('2007-2008', 'Milan'),
            ('2009-2011', 'Corinthians')
        ]
    },
    {
        'name': 'David Beckham',
        'aliases': ['beckham', 'david beckham', 'becks', 'd beckham'],
        'nationality': 'England',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('1992-2003', 'Manchester United'),
            ('2003-2007', 'Real Madrid'),
            ('2007-2012', 'LA Galaxy'),
            ('2009-2009', 'Milan (loan)'),
            ('2010-2010', 'Milan (loan)'),
            ('2013-2013', 'Paris Saint-Germain')
        ]
    },
    {
        'name': 'Andrea Pirlo',
        'aliases': ['pirlo', 'andrea pirlo', 'a pirlo'],
        'nationality': 'Italy',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('1995-1998', 'Brescia'),
            ('1998-2001', 'Inter Milan'),
            ('2001-2011', 'Milan'),
            ('2011-2015', 'Juventus'),
            ('2015-2017', 'New York City FC')
        ]
    },
    {
        'name': 'Paolo Maldini',
        'aliases': ['maldini', 'paolo maldini', 'p maldini'],
        'nationality': 'Italy',
        'position': 'Defender',
        'difficulty': 'hard',
        'path': [
            ('1985-2009', 'Milan')
        ]
    },
    {
        'name': 'Francesco Totti',
        'aliases': ['totti', 'francesco totti', 'f totti', 'er pupone'],
        'nationality': 'Italy',
        'position': 'Forward',
        'difficulty': 'hard',
        'path': [
            ('1992-2017', 'Roma')
        ]
    },
    {
        'name': 'Edinson Cavani',
        'aliases': ['cavani', 'edinson cavani', 'el matador', 'e cavani'],
        'nationality': 'Uruguay',
        'position': 'Striker',
        'difficulty': 'hard',
        'path': [
            ('2005-2007', 'Danubio'),
            ('2007-2010', 'Palermo'),
            ('2010-2013', 'Napoli'),
            ('2013-2020', 'Paris Saint-Germain'),
            ('2020-2022', 'Manchester United'),
            ('2022-2023', 'Valencia'),
            ('2023-now',  'Boca Juniors')
        ]
    },
    {
        'name': 'Luis Suárez',
        'aliases': ['suarez', 'luis suarez', 'luis suárez', 'l suarez'],
        'nationality': 'Uruguay',
        'position': 'Striker',
        'difficulty': 'hard',
        'path': [
            ('2005-2006', 'Nacional'),
            ('2006-2007', 'Groningen'),
            ('2007-2011', 'Ajax'),
            ('2011-2014', 'Liverpool'),
            ('2014-2020', 'Barcelona'),
            ('2020-2022', 'Atlético Madrid'),
            ('2022-2023', 'Grêmio'),
            ('2024-now',  'Inter Miami')
        ]
    },
    {
        'name': 'Yaya Touré',
        'aliases': ['yaya', 'yaya toure', 'yaya touré', 'y toure'],
        'nationality': 'Ivory Coast',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('2001-2003', 'Beveren'),
            ('2003-2005', 'Metalurh Donetsk'),
            ('2005-2006', 'Olympiacos'),
            ('2006-2007', 'Monaco'),
            ('2007-2010', 'Barcelona'),
            ('2010-2018', 'Manchester City')
        ]
    },
    {
        'name': 'Didier Drogba',
        'aliases': ['drogba', 'didier drogba', 'd drogba'],
        'nationality': 'Ivory Coast',
        'position': 'Striker',
        'difficulty': 'hard',
        'path': [
            ('1998-2002', 'Le Mans'),
            ('2002-2003', 'Guingamp'),
            ('2003-2004', 'Marseille'),
            ('2004-2012', 'Chelsea'),
            ('2012-2013', 'Shanghai Shenhua'),
            ('2013-2014', 'Galatasaray'),
            ('2014-2015', 'Chelsea'),
            ('2015-2016', 'Montreal Impact')
        ]
    },
    {
        'name': 'Samuel Eto\'o',
        'aliases': ['etoo', "samuel eto'o", 'samuel etoo', 'eto o', "eto'o", 's etoo'],
        'nationality': 'Cameroon',
        'position': 'Striker',
        'difficulty': 'hard',
        'path': [
            ('1997-2000', 'Real Madrid'),
            ('1998-2000', 'Leganés (loan)'),
            ('2000-2004', 'Mallorca'),
            ('2004-2009', 'Barcelona'),
            ('2009-2011', 'Inter Milan'),
            ('2011-2013', 'Anzhi'),
            ('2013-2014', 'Chelsea'),
            ('2014-2015', 'Everton'),
            ('2015-2017', 'Sampdoria'),
            ('2017-2018', 'Antalyaspor'),
            ('2018-2019', 'Konyaspor'),
            ('2019-2019', 'Qatar SC')
        ]
    },
    {
        'name': 'Iker Casillas',
        'aliases': ['casillas', 'iker casillas', 'i casillas', 'san iker'],
        'nationality': 'Spain',
        'position': 'Goalkeeper',
        'difficulty': 'hard',
        'path': [
            ('1999-2015', 'Real Madrid'),
            ('2015-2020', 'Porto')
        ]
    },
    {
        'name': 'Wayne Rooney',
        'aliases': ['rooney', 'wayne rooney', 'wazza', 'w rooney'],
        'nationality': 'England',
        'position': 'Forward',
        'difficulty': 'hard',
        'path': [
            ('2002-2004', 'Everton'),
            ('2004-2017', 'Manchester United'),
            ('2017-2018', 'Everton'),
            ('2018-2020', 'DC United'),
            ('2020-2021', 'Derby County')
        ]
    },
    {
        'name': 'Petr Čech',
        'aliases': ['cech', 'petr cech', 'petr čech', 'p cech'],
        'nationality': 'Czech Republic',
        'position': 'Goalkeeper',
        'difficulty': 'hard',
        'path': [
            ('1999-2001', 'Chmel Blšany'),
            ('2001-2002', 'Sparta Prague'),
            ('2002-2004', 'Rennes'),
            ('2004-2015', 'Chelsea'),
            ('2015-2019', 'Arsenal')
        ]
    },
    {
        'name': 'Andrea Barzagli',
        'aliases': ['barzagli', 'andrea barzagli', 'a barzagli'],
        'nationality': 'Italy',
        'position': 'Defender',
        'difficulty': 'hard',
        'path': [
            ('2001-2003', 'Ascoli'),
            ('2003-2004', 'Chievo'),
            ('2004-2008', 'Palermo'),
            ('2008-2011', 'Wolfsburg'),
            ('2011-2019', 'Juventus')
        ]
    },
    {
        'name': 'Carlos Tevez',
        'aliases': ['tevez', 'carlos tevez', 'tévez', 'c tevez', 'carlitos'],
        'nationality': 'Argentina',
        'position': 'Forward',
        'difficulty': 'hard',
        'path': [
            ('2001-2004', 'Boca Juniors'),
            ('2005-2006', 'Corinthians'),
            ('2006-2007', 'West Ham'),
            ('2007-2009', 'Manchester United'),
            ('2009-2013', 'Manchester City'),
            ('2013-2015', 'Juventus'),
            ('2015-2016', 'Boca Juniors'),
            ('2017-2017', 'Shanghai Shenhua'),
            ('2018-2021', 'Boca Juniors')
        ]
    },
    {
        'name': 'Roberto Carlos',
        'aliases': ['roberto carlos', 'r carlos', 'roberto'],
        'nationality': 'Brazil',
        'position': 'Defender',
        'difficulty': 'hard',
        'path': [
            ('1991-1993', 'União São João'),
            ('1993-1995', 'Palmeiras'),
            ('1995-1996', 'Inter Milan'),
            ('1996-2007', 'Real Madrid'),
            ('2007-2010', 'Fenerbahçe'),
            ('2010-2011', 'Corinthians'),
            ('2011-2012', 'Anzhi')
        ]
    },
    {
        'name': 'Kaká',
        'aliases': ['kaka', 'kaká', 'ricardo kaka', 'ricardo kaká'],
        'nationality': 'Brazil',
        'position': 'Midfielder',
        'difficulty': 'hard',
        'path': [
            ('2001-2003', 'São Paulo'),
            ('2003-2009', 'Milan'),
            ('2009-2013', 'Real Madrid'),
            ('2013-2014', 'Milan'),
            ('2014-2017', 'Orlando City')
        ]
    },
    {
        'name': 'Gerard Piqué',
        'aliases': ['pique', 'gerard pique', 'piqué', 'g pique'],
        'nationality': 'Spain',
        'position': 'Defender',
        'difficulty': 'hard',
        'path': [
            ('2004-2008', 'Manchester United'),
            ('2006-2007', 'Real Zaragoza (loan)'),
            ('2008-2022', 'Barcelona')
        ]
    },
]


# Build an alias-to-name lookup table for fast matching
ALIAS_TO_PLAYER = {}
for p in PLAYERS:
    canonical = p['name']
    # Always include the canonical name as an alias
    norms = set(p['aliases'])
    norms.add(canonical.lower())
    # also accept name without diacritics handled later
    for alias in norms:
        ALIAS_TO_PLAYER[alias.lower()] = canonical


def get_players_by_difficulty(difficulty: str):
    return [p for p in PLAYERS if p['difficulty'] == difficulty]


def get_all_player_count():
    return len(PLAYERS)
