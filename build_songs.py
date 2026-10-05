"""Builds songs.json from the iTunes Search API (no key needed).

Run: uv run build_songs.py
Every artist in ARTISTS gets their whole iTunes discography (one entry per song,
studio version preferred), written to songs_master.json. The game only ships
songs.json: each artist's PER_ARTIST most-played songs, every song in TRACKS, plus
ids listed in include.txt and minus ids listed in exclude.txt (one id per line,
"#" starts a comment). Find ids by searching songs_master.json for the title. Responses are cached in itunes_cache.json, so
re-runs after editing the lists only fetch what is new.
"""
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from difflib import SequenceMatcher

CACHE = pathlib.Path("itunes_cache.json")
YT_MATCHES = pathlib.Path("youtube_matches.json")
MASTER = pathlib.Path("songs_master.json")  # everything found; stays on this machine
PER_ARTIST = 30  # how many of each artist's songs go into the published songs.json, most played first
KEEP = ("trackId", "trackName", "artistName", "artistId", "previewUrl", "artworkUrl100", "trackViewUrl", "trackTimeMillis")
FIELDS = KEEP + ("collectionName", "releaseDate", "kind")

# (Arabic name shown next to the iTunes one, Latin name used as a fallback query, category)
ARTISTS = [
    # classic
    ("أم كلثوم", "Umm Kulthum", "classic"),
    ("عبد الحليم حافظ", "Abdel Halim Hafez", "classic"),
    ("محمد عبد الوهاب", "Mohammed Abdel Wahab", "classic"),
    ("فريد الأطرش", "Farid Al Atrash", "classic"),
    ("شادية", "Shadia", "classic"),
    ("وردة", "Warda", "classic"),
    ("فيروز", "Fairuz", "classic"),
    ("نجاة الصغيرة", "Najat Al Saghira", "classic"),
    ("فايزة أحمد", "Fayza Ahmed", "classic"),
    ("ميادة الحناوي", "Mayada El Hennawy", "classic"),
    ("محمد فوزي", "Mohamed Fawzi", "classic"),
    ("ليلى مراد", "Leila Mourad", "classic"),
    ("سيد درويش", "Sayed Darwish", "classic"),
    ("محمد رشدي", "Mohamed Roshdy", "classic"),
    ("محمد قنديل", "Mohamed Kandil", "classic"),
    ("سيد مكاوي", "Sayed Mekawy", "classic"),
    ("عفاف راضي", "Afaf Rady", "classic"),
    ("هاني شاكر", "Hany Shaker", "classic"),
    ("علي الحجار", "Ali El Haggar", "classic"),
    ("مدحت صالح", "Medhat Saleh", "classic"),
    # pop
    ("عمرو دياب", "Amr Diab", "pop"),
    ("محمد منير", "Mohamed Mounir", "pop"),
    ("محمد فؤاد", "Mohamed Fouad", "pop"),
    ("مصطفى قمر", "Moustafa Amar", "pop"),
    ("هشام عباس", "Hisham Abbas", "pop"),
    ("إيهاب توفيق", "Ehab Tawfik", "pop"),
    ("حميد الشاعري", "Hamid El Shaeri", "pop"),
    ("عامر منيب", "Amer Mounib", "pop"),
    ("خالد عجاج", "Khaled Agag", "pop"),
    ("شيرين", "Sherine", "pop"),
    ("أنغام", "Angham", "pop"),
    ("تامر حسني", "Tamer Hosny", "pop"),
    ("محمد حماقي", "Mohamed Hamaki", "pop"),
    ("رامي صبري", "Ramy Sabry", "pop"),
    ("رامي جمال", "Ramy Gamal", "pop"),
    ("تامر عاشور", "Tamer Ashour", "pop"),
    ("أحمد سعد", "Ahmed Saad", "pop"),
    ("بهاء سلطان", "Bahaa Sultan", "pop"),
    ("محمد محيي", "Mohamed Mohie", "pop"),
    ("محمود العسيلي", "Mahmoud El Esseily", "pop"),
    ("مصطفى حجاج", "Moustafa Hagag", "pop"),
    ("حمادة هلال", "Hamada Helal", "pop"),
    ("أبو", "Abu", "pop"),
    ("لؤي", "Loai", "pop"),
    ("روبي", "Ruby", "pop"),
    ("آمال ماهر", "Amal Maher", "pop"),
    ("حمزة نمرة", "Hamza Namira", "pop"),
    ("تميم يونس", "Tameem Youness", "pop"),
    ("أكرم حسني", "Akram Hosny", "pop"),
    ("كايروكي", "Cairokee", "pop"),
    ("مسار إجباري", "Massar Egbari", "pop"),
    ("وسط البلد", "Wust El Balad", "pop"),
    ("شارموفرز", "Sharmoofers", "pop"),
    ("توو ليت", "TUL8TE", "pop"),
    # pop from outside Egypt that is on every Egyptian playlist
    ("نانسي عجرم", "Nancy Ajram", "pop"),
    ("إليسا", "Elissa", "pop"),
    ("هيفاء وهبي", "Haifa Wehbe", "pop"),
    ("ميريام فارس", "Myriam Fares", "pop"),
    ("حسين الجسمي", "Hussain Al Jassmi", "pop"),
    ("وائل كفوري", "Wael Kfoury", "pop"),
    ("وائل جسار", "Wael Jassar", "pop"),
    ("راغب علامة", "Ragheb Alama", "pop"),
    ("فضل شاكر", "Fadel Chaker", "pop"),
    ("سعد لمجرد", "Saad Lamjarred", "pop"),
    # shaabi + mahraganat
    ("أحمد عدوية", "Ahmed Adaweya", "shaabi"),
    ("حكيم", "Hakim", "shaabi"),
    ("شعبان عبد الرحيم", "Shaaban Abdel Rahim", "shaabi"),
    ("عبد الباسط حمودة", "Abdel Baset Hamouda", "shaabi"),
    ("حسن الأسمر", "Hassan El Asmar", "shaabi"),
    ("محمود الليثي", "Mahmoud El Leithy", "shaabi"),
    ("أحمد شيبة", "Ahmed Sheba", "shaabi"),
    ("سعد الصغير", "Saad El Soghayar", "shaabi"),
    ("رضا البحراوي", "Reda El Bahrawy", "shaabi"),
    ("كريم محمود عبد العزيز", "Karim Mahmoud Abdelaziz", "shaabi"),
    ("حسن شاكوش", "Hassan Shakosh", "shaabi"),
    ("حمو بيكا", "Hamo Bika", "shaabi"),
    ("عمر كمال", "Omar Kamal", "shaabi"),
    ("أوكا وأورتيجا", "Oka Wi Ortega", "shaabi"),
    ("الصواريخ", "El Sawareekh", "shaabi"),
    ("عصام صاصا", "Essam Sasa", "shaabi"),
    ("محمد رمضان", "Mohamed Ramadan", "shaabi"),
    ("مسلم", "Muslim", "shaabi"),
    ("عنبة", "Enaba", "shaabi"),
    # rap
    ("ويجز", "Wegz", "rap"),
    ("مروان بابلو", "Marwan Pablo", "rap"),
    ("مروان موسى", "Marwan Moussa", "rap"),
    ("أبيوسف", "Abyusif", "rap"),
    ("شاهين", "Shahyn", "rap"),
    ("عفروتو", "Afroto", "rap"),
    ("ليجي سي", "Lege-Cy", "rap"),
    ("أحمد سانتا", "Ahmed Santa", "rap"),
    ("زياد ظاظا", "Ziad Zaza", "rap"),
    ("أحمد مكي", "Ahmed Mekky", "rap"),
    # playlist artists that only had single songs listed before
    ("عمر خيرت", "Omar Khairat", "classic"),
    ("داليدا", "Dalida", "classic"),
    ("لينا شماميان", "Lena Chamamyan", "classic"),
    ("المصريين", "El Masreyeen", "classic"),
    ("حسن أبو السعود", "Hassan Abou El Seoud", "classic"),
    ("حسين الديك", "Hussein Al Deek", "pop"),
    ("جو أشقر", "Joe Ashkar", "pop"),
    ("زياد برجي", "Ziad Bourji", "pop"),
    ("كارول سماحة", "Carole Samaha", "pop"),
    ("ناصيف زيتون", "Nassif Zeytoun", "pop"),
    ("رامي عياش", "Ramy Ayach", "pop"),
    ("الشاب خالد", "Khaled", "pop"),
    ("حمادة نشواتي", "Hamada Nashawaty", "pop"),
    ("كريم نور", "Karim Nour", "pop"),
    ("عبد الفتاح جريني", "Abdel Fattah Grini", "pop"),
    ("إياد طنوس", "Eyad Tannous", "pop"),
    ("علي سمارة", "Ali Samara", "shaabi"),
    ("حسن أبو الروس", "Hassan Abouelrouss", "shaabi"),
    ("سامر المدني", "Samer Elmedany", "shaabi"),
    ("هوبا", "Hooba", "shaabi"),
    ("أبو الليف", "Abou Elleef", "shaabi"),
    ("أحمد عبده", "Ahmed Abdo", "shaabi"),
    ("أحمد الدوجري", "Ahmed El Dogary", "shaabi"),
    ("إسلام ساسو", "Eslam Saso", "shaabi"),
    ("حمادة مجدي", "Hamada Magdy", "shaabi"),
    ("سانت ليفانت", "Saint Levant", "rap"),
]

# Extra spellings Apple files an artist under, when they are too different from the name above to match by themselves.
ALIASES = {
    "أم كلثوم": ["Oum Kalsoum", "Om Kolthoum", "Oum Kalthoum", "Om Kalthoum", "Omme Kolsoum"],
    "فيروز": ["Fairouz"],
    "فريد الأطرش": ["Farid El Atrache"],
    "عبد الحليم حافظ": ["Abd El Halim Hafez"],
    "محمد عبد الوهاب": ["Mohamed Abdel Wahab"],
    "سيد درويش": ["Sayed Darwesh", "Sayed Darweesh"],
}

# Parked: Umm Kulthum essentials that Apple only has as covers (checked 2026-10-05). Her own recordings are on
# YouTube Music, but the game can't cut exact clips from YouTube, so they are left out until that is decided:
#   Fakkarouni, Hayart Albi Maak, Haseebak Lel Zaman, Zalamna El Hob, Habibi Yesaed Awqato

# Specific songs: category -> [(title, main artist)]
TRACKS = {
    "classic": [
        ("Alf Leila We Leila", "Umm Kulthum"), ("انت عمري", "Umm Kulthum"), ("Amal Hayati", "Umm Kulthum"),
        ("يا مسهرني", "Umm Kulthum"), ("حسيبك للزمن", "Umm Kulthum"), ("ودارت الايام", "Umm Kulthum"),
        ("ليلة حب", "Umm Kulthum"), ("ظلمنا الحب", "Umm Kulthum"), ("بعيد عنك", "Umm Kulthum"),
        ("فات الميعاد", "Umm Kulthum"), ("حبيبي يسعد اوقاته", "Umm Kulthum"), ("غنيلي شوي شوي", "Umm Kulthum"),
        ("قال ايه بيسألوني", "Warda"), ("Fe Youm We Leila", "Warda"), ("العيون السود", "Warda"),
        ("Tab Wana Maly", "Warda"), ("Batwanes Beek", "Warda"), ("Haramt Ahebak", "Warda"),
        ("فاتت جنبنا", "Abdel Halim Hafez"), ("نبتدي منين الحكاية", "Abdel Halim Hafez"),
        ("Mawaood", "Abdel Halim Hafez"), ("Zay El Hawa", "Abdel Halim Hafez"), ("Qareat Al Fengan", "Abdel Halim Hafez"),
        ("Ahwak", "Abdel Halim Hafez"), ("Resala Men Taht El Maa", "Abdel Halim Hafez"), ("Toba", "Abdel Halim Hafez"),
        ("حاول تفتكرني", "Abdel Halim Hafez"), ("Ana Lak Ala Toul", "Abdel Halim Hafez"),
        ("Gana El Hawa", "Abdel Halim Hafez"), ("Sawah", "Abdel Halim Hafez"), ("اول مرة تحب يا قلبي", "Abdel Halim Hafez"),
        ("Ala Hesb Wedad", "Abdel Halim Hafez"), ("Bahlam Beek", "Abdel Halim Hafez"), ("لا تكذبي", "Abdel Halim Hafez"),
        ("Saaltak Habiby", "Fairuz"), ("Ana Le Habiby", "Fairuz"), ("Wahdon", "Fairuz"), ("Ya Ana Ya Ana", "Fairuz"),
        ("Nassam Alayna El Hawa", "Fairuz"), ("Kan El Zamaan", "Fairuz"), ("Kan Endena Tahoun", "Fairuz"),
        ("Saalouny El Nas", "Fairuz"), ("Chat Iskandaria", "Fairuz"),
        ("Zourouni Kouli Sanah Marah", "Sayed Darwish"), ("Bayent El Hob Alaya", "Mayada El Hennawy"),
        ("Lamma Bada Yatathana", "Lena Chamamyan"), ("Tabtab Alena Al Hawa", "Shadia"),
        ("Awkat Ashouf Malamhak", "El Masreyeen"), ("قضية عم احمد", "Omar Khairat"),
        ("Helwa Ya Baladi", "Dalida"), ("Shik Shak Shok", "Hassan Abou Seoud"),
    ],
    "pop": [
        ("Eish Besho'ak", "Tamer Hosny"), ("Kol Marra", "Tamer Hosny"), ("Yana Ya Mafish", "Tamer Hosny"),
        ("We Enta Maaya", "Tamer Hosny"), ("Heya Di", "Tamer Hosny"), ("Ya Bent El Eh", "Tamer Hosny"),
        ("Lolak Habiby", "Tamer Hosny"), ("Helm Seneen", "Tamer Hosny"), ("We Akheeran", "Tamer Hosny"),
        ("Ana Wala 3aref", "Tamer Hosny"), ("حلو المكان", "Tamer Hosny"), ("قولي كلام", "Tamer Hosny"),
        ("اختراع", "Tamer Hosny"), ("هرمون السعادة", "Tamer Hosny"), ("Hadalaany", "Tamer Hosny"),
        ("Mn Alby Baghany", "Mohamed Hamaki"), ("Wahda Wahda", "Mohamed Hamaki"), ("احلى حاجة فيكي", "Mohamed Hamaki"),
        ("Oddam El Nas", "Mohamed Hamaki"), ("Ya Sattar", "Mohamed Hamaki"), ("Mayni", "Mohamed Hamaki"),
        ("Aalo Annek", "Mohamed Hamaki"), ("Tak", "Mohamed Hamaki"), ("لمون نعناع", "Mohamed Hamaki"),
        ("Adrenaline", "Mohamed Hamaki"), ("Mabalash", "Mohamed Hamaki"), ("Zayaha Meen", "Mohamed Hamaki"),
        ("و افتكرت", "Mohamed Hamaki"), ("La Malama", "Mohamed Hamaki"), ("كنت تتكلم", "Mohamed Hamaki"),
        ("ناويها", "Mohamed Hamaki"), ("Mel Bedaya", "Mohamed Hamaki"), ("Yalli Zaa'lan", "Mohamed Hamaki"),
        ("Agmal Youm", "Mohamed Hamaki"), ("Wamel Eih", "Mohamed Hamaki"),
        ("Nour El Ein", "Amr Diab"), ("Wala Ala Balo", "Amr Diab"), ("Bayen Habeit", "Amr Diab"),
        ("ليلي نهاري", "Amr Diab"), ("Amarain", "Amr Diab"), ("Tamally Maak", "Amr Diab"), ("جماله", "Amr Diab"),
        ("خلينا نشوفك", "Amr Diab"), ("Welsa Betheboh", "Amr Diab"), ("Al Leila", "Amr Diab"),
        ("آه من الفراق", "Amr Diab"), ("Odam Merayetha", "Amr Diab"),
        ("So Ya So", "Mohamed Mounir"), ("Fi 3esh2 El Banat", "Mohamed Mounir"), ("Ya Hamaam", "Mohamed Mounir"),
        ("Shamandora", "Mohamed Mounir"), ("Ah Yasmarany", "Mohamed Mounir"), ("Leh Ya Donya", "Mohamed Mounir"),
        ("لِلّي", "Mohamed Mounir"), ("Habiby Lola Al Sahar", "Mohamed Mounir"), ("Ana Ba3sha2 El Bahr", "Mohamed Mounir"),
        ("Hara El Saqueen", "Mohamed Mounir"), ("Eqrar", "Mohamed Mounir"),
        ("Sahrany", "Ehab Tawfik"), ("Allah Aleik Ya Seedy", "Ehab Tawfik"), ("Ahla Menhom", "Ehab Tawfik"),
        ("Tetraga Feya", "Ehab Tawfik"), ("Malhomsh Fel Tayeb", "Ehab Tawfik"),
        ("Habeb Hayaty", "Moustafa Amar"), ("اسكندراني", "Moustafa Amar"), ("السود عيونه", "Moustafa Amar"),
        ("Haollak Eih", "Moustafa Amar"), ("Lesa Habaib", "Moustafa Amar"),
        ("Mabrouk Alina", "Ramy Sabry"), ("Taali", "Ramy Sabry"), ("بطلي بقى", "Ramy Sabry"),
        ("Enty Genan", "Ramy Sabry"), ("يمكن خير", "Ramy Sabry"), ("Hayaty Msh Tamam", "Ramy Sabry"),
        ("Ana Baatereflek", "Ramy Sabry"), ("Shattabna", "Ramy Sabry"),
        ("Ya Nas", "Mahmoud El Esseily"), ("7elm B3eed", "Mahmoud El Esseily"), ("Fe Hetta Tanya", "Mahmoud El Esseily"),
        ("Dom Dom", "Mahmoud El Esseily"), ("Hob Ghalat", "Mahmoud El Esseily"), ("كده كده بايظه", "Mahmoud El Esseily"),
        ("Amoot Ana", "Mahmoud El Esseily"), ("حبيبي وابن حبيبي", "Mahmoud El Esseily"), ("Tararam", "Mahmoud El Esseily"),
        ("Ya Medalaa", "Ahmed Saad"), ("اليوم الحلو ده", "Ahmed Saad"), ("اختياراتي", "Ahmed Saad"),
        ("Kolo Falso", "Ahmed Saad"), ("Ya Layaly", "Ahmed Saad"), ("Sayrena Ya Donia", "Ahmed Saad"),
        ("El Wad Albo Beyewga3o", "Bahaa Sultan"), ("براحة يا شيخة", "Bahaa Sultan"), ("Ta3ala Adalla3ak", "Bahaa Sultan"),
        ("الجو ولع", "Bahaa Sultan"), ("اما اتكلم", "Bahaa Sultan"),
        ("كتر خيري", "Sherine"), ("Sabry Aalil", "Sherine"), ("الوتر الحساس", "Sherine"), ("كلام عينيه", "Sherine"),
        ("ليه بيداري كده", "Ruby"), ("Alby Plastic", "Ruby"), ("Namet Nenna", "Ruby"),
        ("Yamnana", "Moustafa Hagag"), ("Khatawa", "Moustafa Hagag"), ("Ah Ya Hanan", "Moustafa Hagag"),
        ("Mafeesh Menha", "Ramy Gamal"), ("Sa'af", "Ramy Gamal"),
        ("3 Daqat", "Abu"), ("Habibi Ya Leil", "Abu"), ("Hateegy", "Abu"),
        ("Habiby Da", "Hisham Abbas"), ("Habibi Ya", "Mohamed Fouad"), ("El Hob El Ha2e2y", "Mohamed Fouad"),
        ("Fady Shewaya", "Hamza Namira"), ("بتحبيني", "Hamid Al Shaeri"), ("W Nefdal Norkos", "Angham"),
        ("Bahebbak", "Mohamed Mohie"), ("بحبك و خايف", "Tamer Ashour"), ("Aamel Eh Fe Hayatak", "Amer Mounib"),
        ("شكا", "خالد عجاج"), ("اه يا عيني يا ليل", "Loai"), ("اه يا شوق", "Loai"),
        ("Sponge Bob", "Hamada Helal"), ("Mastoul", "Hamada Helal"), ("Shakle Habetek", "Hamada Nashawaty"),
        ("Aleb Albi", "Karim Nour"), ("اشوف فيك يوم", "Abd El Fattah Grini"), ("بأمارة مين", "Farid"),
        ("الدنيا زى المرجيحة", "عمرو السعيد"), ("حبيبت ابوها", "محمد سلطان"), ("مسيطره", "Lamis Kan"),
        ("ستو أنا", "Akram Hosny"), ("زامباهولا", "Akram Hosny"), ("حضرات السادة", "Akram Hosny"),
        ("تراك الموسم", "Tameem Youness"), ("سالمونيلا", "Tameem Youness"), ("كاجولوه", "محمد هنيدي"),
        ("El Hob Gany", "TUL8TE"),
        ("Ah W Noss", "Nancy Ajram"), ("Ya Tabtab Wa Dallaa", "Nancy Ajram"), ("Badna Nwalee El Jaw", "Nancy Ajram"),
        ("شخبط شخابيط", "Nancy Ajram"), ("Helm El Banat", "Nancy Ajram"), ("Albi Ya Albi", "Nancy Ajram"),
        ("على شانك", "Nancy Ajram"), ("Akhasmak Ah", "Nancy Ajram"), ("Enta Eih", "Nancy Ajram"),
        ("Piece Of My Heart", "Hussain Al Jassmi"), ("Bel Bont El3areedh", "Hussain Al Jassmi"),
        ("Boushret Kheir", "Hussain Al Jassmi"), ("بحبك وحشتيني", "Hussain Al Jassmi"),
        ("ستة الصبح", "Hussain Al Jassmi"), ("Balbata", "Hussain Al Jassmi"), ("Ser Alsada", "Hussain Al Jassmi"),
        ("اللي باعنا", "Ragheb Alama"), ("Nassiny El Donia", "Ragheb Alama"), ("Albi Eshi'ha", "Ragheb Alama"),
        ("Ghareibah El Nas", "Wael Jassar"), ("Mshit Khalas", "Wael Jassar"), ("Betewhasheiny", "Wael Jassar"),
        ("El Bint El Awiye", "Wael Kfoury"), ("قلبى مشتاق", "Wael Kfoury"),
        ("اجمل احساس", "Elissa"), ("Min Awel Dekika", "Elissa"), ("Ensay", "Saad Lamjarred"),
        ("بابا فين", "Haifa Wehbe"), ("الواوا", "Haifa Wehbe"), ("Waheshni Eh", "Myriam Fares"),
        ("Ya Ghayeb", "Fadel Chaker"), ("قصة حب", "Ramy Ayach"), ("Shou Helou", "Ziad Bourji"),
        ("Esma'ny", "Carole Samaha"), ("Mahlaki", "Hussein Al Deek"), ("El Waed Waed", "Hussein Al Deek"),
        ("حبيبة قلبي", "Joe Ashkar"), ("Habibet Alby", "Joe Ashkar"), ("Takke", "Nassif Zeytoun"),
        ("إنت زعلان مني", "Eyad Tannous"), ("مخصماك", "Nawal"), ("C'est La Vie", "Khaled"), ("Hiya Hiya", "Khaled"),
        ("Ya Nour El Ein", "Massari"),
    ],
    "shaabi": [
        ("El Hantoor", "Saad El Soghayar"), ("Hatgawez", "Saad El Soghayar"), ("العنب", "Saad El Soghayar"),
        ("Howa Enta Tlea't Menhom", "Saad El Soghayar"), ("Erosy W Ra'seena", "Saad El Soghayar"),
        ("ارقص ياعم صابر", "Saad El Soghayar"),
        ("Ah Ya Alby", "Hakim"), ("Yaho", "Hakim"), ("Wala Wahed", "Hakim"), ("El Salamou Aleikom", "Hakim"),
        ("Raqasony", "Hakim"),
        ("Elghazala Ray2a", "Karim Mahmoud Abdelaziz"), ("قلب قلبي", "Karim Mahmoud Abdelaziz"),
        ("لغبطيطا", "Omar Kamal"), ("انتي معلمه", "Omar Kamal"), ("السخان", "Omar Kamal"),
        ("Oud Al batal", "Hassan Shakosh"), ("Baskotaya M2armesha", "Hassan Shakosh"),
        ("Mahragan Bent El Geran", "Hassan Shakosh"), ("Salka", "Hassan Shakosh"),
        ("Mahragan Adl3y Ya Moza", "Hassan Shakosh"), ("قمبلة الجيل", "Hassan Shakosh"),
        ("تعالالي حبيبي الليلة", "Hassan Shakosh"), ("انتى الوحش", "Hassan Shakosh"),
        ("قمر التيكتوكايه", "Hamo Bika"), ("اي مس يو فري هارت", "Hamo Bika"),
        ("Mahragan Ayem Fe Bahr El Ghadr", "Ali Samara"), ("Bonbonaya", "Mahmoud El Leithy"),
        ("Ya Habibi", "Mohamed Ramadan"), ("رايحين نسهر", "Mohamed Ramadan"),
        ("Falatet Meny", "Hassan Abouelrouss"), ("Khalsana M3ako B Sheyaka", "Samer Elmedany"),
        ("Mahragan Laa", "El Sawareekh"), ("Ekhwaty", "El Sawareekh"), ("Hagareen Ala El Shesha", "Hooba"),
        ("Dola Maganeen", "Abou Elleef"), ("سطلانة", "Abd El Basset Hamouda"), ("Fi 7eta Tanya", "Abd El Basset Hamouda"),
        ("مهرجان السكة التانية", "Ahmed Abdo"), ("مهرجان فتشني يا باشا فتشني", "Ahmed El Dogary"),
        ("هات سيجاره", "مهرجان"), ("Ana Msh Faker El Kobleh", "G. Oka"), ("قالتلي لا لا", "Eslam Saso"),
    ],
    "rap": [
        ("بعودة يا بلادي", "Wegz"), ("البخت", "Wegz"), ("KALAMANTINA", "Saint Levant"),
    ],
}

# Never wanted: someone else's take on the song.
DROP = re.compile(r"remix|rework|cover|karaoke|\bmix\b|mixed by|medley|mashup|tribute|chill|lounge|lo-?fi|ريمكس|كاريوكي|توزيع|ميكس", re.I)
# Modern acts credited alongside a classic artist on what are really remixes. Duets between classic artists are fine,
# so this is a list of names rather than a rule; add to it when another one turns up.
BAD_CREDIT = re.compile(r"blu rapture|sanwal khan|oka el-afret|ammar godza|ata animation", re.I)
# Alternate takes: kept only when the artist has no plain version of the same title.
ALT = re.compile(r"live|instrumental|version|acoustic|intro|outro|\bpt\b|part|حفل|لايف|موسيقى|مقطع", re.I)

cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def norm(text):
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text.lower())
    return re.sub(r"\W+", "", text)


def title_key(title):
    return norm(ALT.sub("", title))


def save_cache():
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fetch(path, q, keep):
    """GET an iTunes endpoint, cached on disk; returns the results trimmed to `keep` fields."""
    key = q if path == "search" else f"{path}?{q}"  # search keys predate lookup; keep them valid
    if key in cache:
        return cache[key]
    for _ in range(5):
        try:
            with urllib.request.urlopen(f"https://itunes.apple.com/{path}?{q}", timeout=30) as r:
                results = [{k: x.get(k) for k in keep} for x in json.load(r)["results"]]
            time.sleep(3.1)  # API allows ~20 calls/minute
            cache[key] = [x for x in results if x.get(keep[0])]
            if len(cache) % 20 == 0:
                save_cache()
            return cache[key]
        except Exception as e:
            print(f"  retrying {path}: {e}", file=sys.stderr)
            time.sleep(30)
    return []


def query(term, **extra):
    return urllib.parse.urlencode({"term": re.sub("[أإآ]", "ا", term), "country": "eg", **extra})


def search(term, attribute="artistTerm", limit=100):
    extra = {"media": "music", "entity": "song", "limit": limit}
    if attribute:
        extra["attribute"] = attribute
    return [x for x in fetch("search", query(term, **extra), KEEP) if x["previewUrl"]]


def lookup(ids):
    """Album, release date and length for up to 200 track ids per call (used for hints)."""
    q = urllib.parse.urlencode({"id": ",".join(map(str, ids)), "country": "eg"})
    return {x["trackId"]: x for x in fetch("lookup", q, ("trackId", "collectionName", "releaseDate", "trackTimeMillis"))}


def artist_ids(ar, latin):
    """Every iTunes artist entry that is this artist (Apple often splits one artist across spellings)."""
    ids = set()
    by_ar = search(ar)
    top = Counter(r["artistId"] for r in (by_ar if len(by_ar) >= 5 else by_ar + search(latin))).most_common(1)
    if top:
        ids.add(top[0][0])
    names = [latin, *ALIASES.get(ar, [])]
    for term in (ar, *names):
        for x in fetch("search", query(term, entity="musicArtist", limit=5), ("artistId", "artistName")):
            name = norm(x["artistName"])
            if name == norm(ar) or any(SequenceMatcher(None, norm(n), name).ratio() >= 0.8 for n in names):
                ids.add(x["artistId"])
    return ids


def discography(ids, ar, latin):
    """All of the artist's tracks: one lookup per artist entry, plus paged searches when a lookup hits its 200 cap."""
    out, capped = {}, False
    for aid in ids:
        got = fetch("lookup", urllib.parse.urlencode({"id": aid, "entity": "song", "limit": 200, "country": "eg"}), FIELDS)
        # a lookup also returns other acts' tracks that sample or "feature" this artist: keep only the artist's own
        out.update((r["trackId"], r) for r in got if r["artistId"] in ids)
        capped |= len(got) >= 200
    if capped:
        for term in (ar, latin):
            for offset in range(0, 1000, 200):
                page = fetch("search", query(term, media="music", entity="song", attribute="artistTerm", limit=200, offset=offset), FIELDS)
                fresh = [r for r in page if r["artistId"] in ids and r["trackId"] not in out]
                out.update((r["trackId"], r) for r in fresh)
                if len(page) < 200 or not fresh:
                    break
    return list(out.values())


def select(tracks):
    """One recording per title: no remixes or covers, and a live/alternate take only if nothing plainer exists."""
    best = {}
    for r in tracks:
        title = r["trackName"] or ""
        if (r.get("kind") != "song" or not r.get("previewUrl") or (r.get("trackTimeMillis") or 0) < 60_000
                or DROP.search(title) or DROP.search(r.get("collectionName") or "") or BAD_CREDIT.search(r.get("artistName") or "")):
            continue
        key, alt = title_key(title), bool(ALT.search(title))
        if key and (key not in best or (best[key][0] and not alt)):
            best[key] = (alt, r)
    return [r for _, r in best.values()]


def find_track(title, artist, ids_of):
    """The playlist song on iTunes, by that artist only (a matching title by someone else is a cover or a sample)."""
    close = [ids for name, ids in ids_of.items() if SequenceMatcher(None, norm(artist), norm(name)).ratio() >= 0.8]
    own = set().union(*close) if close else None
    ok = [
        r for r in search(f"{title} {artist}", attribute=None, limit=10)
        if (r["artistId"] in own if own is not None
            else norm(title) in norm(r["trackName"]) if not artist.isascii()
            else SequenceMatcher(None, norm(artist), norm(r["artistName"])).ratio() >= 0.8)
    ]
    ok.sort(key=lambda r: bool(DROP.search(r["trackName"]) or ALT.search(r["trackName"])))
    return ok[0] if ok else None


AR_SOUNDS = {"ب": "b", "ت": "t", "ث": "s", "ج": "g", "ح": "h", "خ": "x", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ش": "c",
             "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "غ": "g", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h"}
FRANCO = [("sh", "c"), ("ch", "c"), ("kh", "x"), ("gh", "g"), ("th", "s"), ("dh", "d"), ("ph", "f"), ("7", "h"), ("5", "x"), ("8", "g"),
          ("9", "s"), ("j", "g"), ("q", "k"), ("c", "k"), ("p", "b"), ("v", "f")]


def skeleton(text):
    """The consonant sounds of a title, so Arabic script and Franco/Latin spellings of it can be compared.
    ponytail: letter-by-letter and Egyptian-leaning (ج = g); good for telling songs apart, not a real transliterator."""
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text.lower())
    if text.isascii():
        text = text.replace("sh", "\0").replace("ch", "\0")  # protect before c -> k
        for a, b_ in FRANCO[2:]:
            text = text.replace(a, b_)
        out = re.sub(r"[^b-df-hj-np-tvxz\0]", "", text).replace("\0", "c")  # drop vowels, y, w, digits, spaces
    else:
        out = "".join(AR_SOUNDS.get(ch, "") for ch in text)
    return re.sub(r"(.)\1+", r"\1", out)


def titles_agree(yt_title, apple_title):
    """Whether YouTube's title names the same song: True, False, or None when there isn't enough to go on.
    Same alphabet: compare the text. Different alphabets: compare how they sound."""
    if not yt_title:
        return None
    latin = apple_title.isascii()
    part = norm(re.sub(r"[^\x00-\x7f]" if latin else r"[\x00-\x7f]", " ", yt_title))  # the part of YouTube's title in Apple's alphabet
    ours = norm(apple_title)
    if len(part) >= 3 and len(ours) >= 3:
        return part in ours or ours in part or SequenceMatcher(None, part, ours).ratio() >= 0.5
    a, b_ = skeleton(yt_title), skeleton(apple_title)
    if not a or not b_:
        return None
    # when unsure, say no: a rejected match only costs that song its full-length player
    return a in b_ or b_ in a or SequenceMatcher(None, a, b_).ratio() >= 0.6


def id_list(name):
    p = pathlib.Path(name)
    return {int(m.group()) for line in (p.read_text().splitlines() if p.exists() else []) if (m := re.match(r"\d+", line.strip()))}


def publish(songs):
    """The shipped subset: per artist, the PER_ARTIST most-played songs plus playlist songs and include.txt, minus exclude.txt."""
    include, exclude, by_artist = id_list("include.txt"), id_list("exclude.txt"), {}
    for s in songs:
        by_artist.setdefault(s["ar"] or s["a"], []).append(s)
    out = []
    for group in by_artist.values():
        ranked = sorted(group, key=lambda s: -s.get("n", 0))  # stable sort: iTunes order breaks ties
        # two spellings of one song match the same YouTube video: publish only the first
        seen = set()
        ranked = [s for s in ranked if not (s.get("yt") in seen or seen.add(s.get("yt") or s["id"]))]
        out += [
            {k: v for k, v in s.items() if k not in ("must", "n")}  # internal fields stay in the master
            for i, s in enumerate(ranked)
            if (i < PER_ARTIST or s.get("must") or s["id"] in include) and s["id"] not in exclude
        ]
    return out


def main():
    songs, ids, titles, known, index, ids_of, lengths = [], set(), set(), {}, {}, {}, {}  # known: artistId -> Arabic name; ids_of: Latin name -> artist ids

    def add(r, ar, cat):
        key = (title_key(r["trackName"]), r["artistId"])
        same = (ar or r["artistName"], r.get("trackTimeMillis"))  # same artist, same length to the millisecond: same recording
        if r["trackId"] in ids or key in titles or same in lengths:
            index.setdefault(key, lengths.get(same, 0))
            return False
        ids.add(r["trackId"])
        titles.add(key)
        index[key] = lengths[same] = len(songs)
        songs.append({
            "id": r["trackId"], "t": r["trackName"], "a": r["artistName"], "aid": r["artistId"], "ar": ar,
            "c": cat, "p": r["previewUrl"], "img": r["artworkUrl100"], "u": r["trackViewUrl"],
            "al": r.get("collectionName") or "", "y": int((r.get("releaseDate") or "0")[:4]),
            "d": round((r.get("trackTimeMillis") or 0) / 1000),
        })
        return True

    for ar, latin, cat in ARTISTS:
        aids = artist_ids(ar, latin)
        known.update((a, ar) for a in aids)
        ids_of[latin] = aids
        ids_of.update((alias, aids) for alias in ALIASES.get(ar, []))
        n = sum(add(r, ar, cat) for r in select(discography(aids, ar, latin)))
        print(f"{n:4d}  {latin}", file=sys.stderr, flush=True)

    rescued, missing = [], []
    for cat, tracks in TRACKS.items():
        for title, artist in tracks:
            r = find_track(title, artist, ids_of)
            if not r:
                missing.append(f"{title} - {artist}")
            else:
                if add(r, known.get(r["artistId"], ""), cat):
                    rescued.append(f"{title} - {artist}")
                songs[index[(title_key(r["trackName"]), r["artistId"])]]["must"] = True

    need = [s for s in songs if not s["y"]]
    extra = {}
    for i in range(0, len(need), 200):
        extra.update(lookup([s["id"] for s in need[i:i + 200]]))
    for s in need:
        e = extra.get(s["id"], {})
        s["al"] = e.get("collectionName") or ""
        s["y"] = int((e.get("releaseDate") or "0")[:4])

    # official YouTube audio found by match_youtube.py: the full song for the end-of-round player, and its play count
    yt = json.loads(YT_MATCHES.read_text()) if YT_MATCHES.exists() else {}
    for s in songs:
        m = yt.get(str(s["id"]))
        if m and titles_agree(m.get("t"), s["t"]) is not False:
            s["yt"], s["n"] = m["v"], m.get("n", 0)
            if m.get("t") and m["t"].isascii() != s["t"].isascii() and titles_agree(m["t"], s["t"]):
                s["t2"] = m["t"]  # YouTube's title in the other alphabet, confirmed to sound the same: searchable either way

    # One YouTube video claimed by two clearly different songs means at least one match is wrong (the matcher goes by
    # artist and length). We can't tell which, so neither keeps it; they fall back to the Apple preview.
    claims = {}
    for s in songs:
        if "yt" in s:
            claims.setdefault(s["yt"], []).append(s)
    conflicts = 0
    for group in claims.values():
        titles = [norm(s["t"]) for s in group]
        if any(a.isascii() == b.isascii() and SequenceMatcher(None, a, b).ratio() < 0.5
               for i, a in enumerate(titles) for b in titles[i + 1:]):
            conflicts += len(group)
            for s in group:
                del s["yt"], s["n"]
    print(f"{conflicts} songs lost their YouTube match because another song claimed the same video", file=sys.stderr)

    save_cache()
    assert songs and len(ids) == len(songs)
    MASTER.write_text(json.dumps(songs, ensure_ascii=False, indent=0), encoding="utf-8")
    published = publish(songs)
    with open("songs.json", "w", encoding="utf-8") as f:
        json.dump(published, f, ensure_ascii=False, indent=0)
    print(f"\n{len(songs)} songs -> {MASTER}, {len(published)} of them published -> songs.json", file=sys.stderr)
    print(f"{len(rescued)} playlist songs the artist crawl missed, added individually", file=sys.stderr)
    print(f"{len(missing)} playlist songs not found on iTunes:\n  " + "\n  ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    finally:
        save_cache()
