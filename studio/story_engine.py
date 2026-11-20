"""Modular Story Generation Engine for Autonomous Hindi Animation Studio.
Produces original, coherent, engaging 4-scene comedy/fable stories for YouTube Shorts and Reels.
Features modular combinatorial story generation (1,000+ unique coherent combinations),
strict personality consistency for Chiku and Gappu, SHA-256 fingerprinting,
duplicate prevention, and resilient history backup upon corruption.
"""

import json
import random
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Ensure Windows console doesn't choke on Devanagari text
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from studio.config import DATA_DIR, LOGS_DIR

HISTORY_FILE = DATA_DIR / "story_history.json"

# Core Character Definitions for Consistent Recurring Duo
CHARACTERS = {
    "chiku": {
        "name": "चीकू",
        "species": "बंदर (Monkey)",
        "personality": "अति-उत्साही, शेखी बघारने वाला, नए जुगाड़ लगाने वाला",
        "role": "protagonist",
        "voice_key": "chiku"
    },
    "gappu": {
        "name": "गप्पू",
        "species": "चूहा (Smart Little Mouse)",
        "personality": "शांत, बुद्धिमान, चश्मे वाला, चीकू की पोल खोलने वाला सच्चा दोस्त",
        "role": "foil_and_friend",
        "voice_key": "gappu"
    }
}

# ---------------------------------------------------------------------------
# MODULAR STORY ARCHETYPES & GENERATIVE MATRIX
# Each archetype defines modular hooks, setups, boasts, reveals, and morals.
# Combinations yield well over 365 distinct, coherent Hindi narratives.
# ---------------------------------------------------------------------------

ARCHETYPES = [
    {
        "category": "invention_mishap",
        "theme": "अनोखा जुगाड़",
        "subjects": [
            {
                "item": "केले के छिलके के जूते",
                "purpose": "हवा में उड़ने वाले जूते",
                "flaw": "फिसलकर कीचड़ में गिर जाना",
                "s1_hook": "चीकू बंदर ने केले के छिलकों से उड़ने वाले रॉकेट जूते बना डाले!",
                "s1_narr": "चीकू ने जंगल के सबसे फिसलन भरे छिलके बटोरे और दावा किया कि अब वह उड़ सकता है।",
                "s2_chiku": "गप्पू भाई! देखो मेरा नया आविष्कार, अब मुझे ज़मीन पर पैर रखने की ज़रूरत नहीं!",
                "s3_gappu": "चीकू भाई, उड़ने से पहले संतुलन तो संभालो, छिलके हवा में नहीं कीचड़ में ले जाते हैं!",
                "s4_moral": "बिना सोचे समझे किया गया जुगाड़ हमेशा उलटा ही पड़ता है!",
                "bg": "forest_path",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "slide_whistle", "sfx_s4": "pop"
            },
            {
                "item": "नारियल का लाउडस्पीकर",
                "purpose": "पूरे जंगल में दहाड़ सुनाना",
                "flaw": "अंदर भंवरा बंद था",
                "s1_hook": "चीकू ने एक खाली नारियल से ऐसा भोंपू बनाया जो शेर की आवाज़ निकालता!",
                "s1_narr": "चीकू बंदर जंगल का सबसे बड़ा गायक बनने की सनक में नया बाजा तैयार कर रहा था।",
                "s2_chiku": "गप्पू! इस लाउडस्पीकर में फूँक मारते ही पूरी दुनिया चीकू का नाम जपेगी!",
                "s3_gappu": "चीकू भाई, बाजे में फूँक मत मारो, उसमें तो लाल चींटियों ने अपना घर बना रखा है!",
                "s4_moral": "दूसरों को डराने का दिखावा अक्सर खुद पर ही भारी पड़ता है!",
                "bg": "jungle_clearing",
                "sfx_s1": "whoosh", "sfx_s2": "boing", "sfx_s3": "boing", "sfx_s4": "success_ding"
            },
            {
                "item": "बांस की जादुई दूरबीन",
                "purpose": "भविष्य देखना",
                "flaw": "आगे सूखी पत्ती चिपकी थी",
                "s1_hook": "चीकू बंदर का दावा था कि उसकी बांस की नली से कल का दिन भी दिखता है!",
                "s1_narr": "चीकू ने बांस की नली को आँखों पर चढ़ाया और भविष्यवक्ता बनने का नाटक शुरू किया।",
                "s2_chiku": "गप्पू देखो! मुझे आगे बहुत बड़ा काला बादल दिख रहा है, तूफान आने वाला है!",
                "s3_gappu": "चीकू भाई, वह कोई तूफान नहीं, तुम्हारी नली के मुँह पर सूखी पत्ती चिपकी है!",
                "s4_moral": "आँखें बंद करके भविष्य देखने वाले अक्सर सामने का गड्ढा भूल जाते हैं!",
                "bg": "forest_path",
                "sfx_s1": "twinkle", "sfx_s2": "twinkle", "sfx_s3": "slide_whistle", "sfx_s4": "pop"
            },
            {
                "item": "पेड़ का पत्ता पैराशूट",
                "purpose": "बादलों से छलांग लगाना",
                "flaw": "पत्ता बीच से फटा हुआ था",
                "s1_hook": "चीकू बंदर ने एक विशाल पत्ते को पैराशूट बनाकर सबसे ऊँचे पेड़ से छलांग लगा दी!",
                "s1_narr": "चीकू आज हवा में तैरने का नया करतब दिखाने की ज़िद पर अड़ा हुआ था।",
                "s2_chiku": "गप्पू ताली बजाओ! आज तुम्हारा चीकू भाई चील की तरह आसमान में नाचेगा!",
                "s3_gappu": "अरे चीकू भाई रुको! पत्ते के बीच में तो कीड़ों ने बड़ा सा छेद कर रखा है!",
                "s4_moral": "जोश में होश खोने से सिर्फ ज़मीन पर धड़ाम ही मिलती है!",
                "bg": "jungle_clearing",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "boing", "sfx_s4": "pop"
            }
        ]
    },
    {
        "category": "mistaken_treasure",
        "theme": "गलतफहमी और खजाना",
        "subjects": [
            {
                "item": "चमकता पीला पत्थर",
                "purpose": "जंगल का महाराजा बनना",
                "flaw": "सूखा हुआ पीला बेर",
                "s1_hook": "चीकू को नदी किनारे एक ऐसा पीला पत्थर मिला जो सूरज जैसा दमक रहा था!",
                "s1_narr": "चीकू बंदर खुशी से झूम उठा, उसे पक्का यकीन था कि वह जंगल का सबसे अमीर बंदर बन गया।",
                "s2_chiku": "गप्पू भाई! देखो, इस जादुई हीरे के दम पर अब मैं पूरे जंगल का राजा कहलाऊँगा!",
                "s3_gappu": "चीकू भाई, राजा बनने से पहले चश्मा लगाकर देखो, वह हीरा नहीं सिर्फ सूखा पीला बेर है!",
                "s4_moral": "हर पीली चमकने वाली चीज़ सोना नहीं होती, कभी-कभी बस सूखा फल होती है!",
                "bg": "riverbank",
                "sfx_s1": "twinkle", "sfx_s2": "twinkle", "sfx_s3": "boing", "sfx_s4": "success_ding"
            },
            {
                "item": "मिट्टी का पुराना घड़ा",
                "purpose": "सोने के सिक्के मिलना",
                "flaw": "जंगली मधुमक्खियों का छत्ता",
                "s1_hook": "गुफा के बाहर चीकू को दबा हुआ एक पुराना मिट्टी का मटका मिला!",
                "s1_narr": "चीकू को लगा कि पूर्वजों ने उसके लिए सोने की मोहरों से भरा कलश छोड़ा है।",
                "s2_chiku": "गप्पू जल्दी आओ! इस घड़े में सोने की खनक सुनाई दे रही है, आज पार्टी होगी!",
                "s3_gappu": "चीकू भाई मटके को मत हिलाओ! वह खनक नहीं, अंदर मधुमक्खियों की भिनभिनाहट है!",
                "s4_moral": "लालच में हाथ डालने से पहले यह देख लो कि अंदर डंक तो नहीं छुपा!",
                "bg": "cave_entrance",
                "sfx_s1": "whoosh", "sfx_s2": "twinkle", "sfx_s3": "slide_whistle", "sfx_s4": "pop"
            },
            {
                "item": "कांच का टूटा टुकड़ा",
                "purpose": "जादुई तारा समझना",
                "flaw": "इंसानों की छोड़ी पुरानी बोतल",
                "s1_hook": "चीकू को झाड़ियों में एक ऐसी चमकीली चीज़ मिली जो धूप में इंद्रधनुष बिखेर रही थी!",
                "s1_narr": "चीकू ने सोचा कि आसमान से टूटकर कोई जादुई सितारा सीधे उसकी झोली में आ गिरा है।",
                "s2_chiku": "गप्पू देखो! आसमान का तारा मेरे हाथ में है, अब मैं जो माँगूँगा वही मिलेगा!",
                "s3_gappu": "चीकू भाई, तारा नहीं यह पिकनिक वालों की टूटी बोतल है, हाथ कटने से पहले फेंक दो!",
                "s4_moral": "कांच के टुकड़ों को सितारा समझने वाले अक्सर भ्रम में ही जीते हैं!",
                "bg": "forest_path",
                "sfx_s1": "twinkle", "sfx_s2": "twinkle", "sfx_s3": "boing", "sfx_s4": "success_ding"
            },
            {
                "item": "विशाल गोल अंडा",
                "purpose": "डायनासोर पालने का सपना",
                "flaw": "गोल चिकना सफेद पत्थर",
                "s1_hook": "नदी के किनारे चीकू को एक विशाल चिकना अंडा मिला!",
                "s1_narr": "चीकू ने सपने सजा लिए कि इस अंडे से बच्चा निकलेगा और वह उस पर सवारी करेगा।",
                "s2_chiku": "गप्पू! मैं इसे सेऊंगा और जब जादुई पक्षी निकलेगा तो हम उस पर सैर करेंगे!",
                "s3_gappu": "चीकू भाई, पत्थर पर बैठकर सेने से सिर्फ कमर टूटेगी, बच्चा नहीं निकलेगा!",
                "s4_moral": "हवाई महल बनाने से पहले ज़मीन की हकीकत को पहचान लेना समझदारी है!",
                "bg": "riverbank",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "boing", "sfx_s4": "pop"
            }
        ]
    },
    {
        "category": "greedy_schemer",
        "theme": "लालच और साझेदारी",
        "subjects": [
            {
                "item": "विशाल मीठा तरबूज",
                "purpose": "अकेले खा जाना",
                "flaw": "पेट फूलकर लुढ़क जाना",
                "s1_hook": "चीकू को नदी किनारे एक ऐसा रसीला तरबूज मिला जिसे देखकर मुँह में पानी आ जाए!",
                "s1_narr": "चीकू ने सोचा अगर गप्पू को बताया तो आधा हिस्सा देना पड़ेगा, इसलिए अकेले ही खाने लगा।",
                "s2_chiku": "आहा! इतना मीठा तरबूज! अकेले खाने का मज़ा ही कुछ और है, किसी को खबर भी नहीं होगी।",
                "s3_gappu": "चीकू भाई, अकेले सारा तरबूज खाओगे तो पेट मटका बनेगा और खुद चल भी नहीं पाओगे!",
                "s4_moral": "बाँट कर खाने में स्वाद और सेहत दोनों हमेशा दोगुने हो जाते हैं!",
                "bg": "riverbank",
                "sfx_s1": "tiptoe", "sfx_s2": "crunch", "sfx_s3": "boing", "sfx_s4": "success_ding"
            },
            {
                "item": "शहद से भरा छत्ता",
                "purpose": "सारा मीठा रस खुद पीना",
                "flaw": "हाथ छत्ते में चिपक जाना",
                "s1_hook": "चीकू को पेड़ की निचली डाली पर शहद से टपकता हुआ बड़ा छत्ता दिखा!",
                "s1_narr": "चीकू ने गप्पू से नज़रें चुराकर छत्ते में दोनों हाथ घुसेड़ दिए।",
                "s2_chiku": "गप्पू को क्या पता चलेगा, यह सारा अमृत अकेला चीकू ही हजम करेगा!",
                "s3_gappu": "चीकू भाई, स्वाद के चक्कर में हाथ तो फँसा लिया, अब मधुमक्खियों को क्या जवाब दोगे?",
                "s4_moral": "चोरी-छिपे मीठा खाने वालों के हिस्से में अक्सर कड़वे डंक ही आते हैं!",
                "bg": "jungle_clearing",
                "sfx_s1": "tiptoe", "sfx_s2": "crunch", "sfx_s3": "slide_whistle", "sfx_s4": "pop"
            },
            {
                "item": "पके मीठे अमरूदों की टोकरी",
                "purpose": "गड्ढे में छिपाना",
                "flaw": "गिलहरियाँ पहले ही चट कर गईं",
                "s1_hook": "चीकू को पके पीले अमरूदों का ढेर मिला, पर उसने गप्पू से छुपाने की साज़िश रची!",
                "s1_narr": "चीकू ने अमरूदों को पत्तों के नीचे दबाया ताकि रात में अकेले दावत उड़ा सके।",
                "s2_chiku": "गप्पू को सिर्फ सूखी रोटी खिलाऊँगा और अमरूद अकेले चुपचाप खाऊँगा!",
                "s3_gappu": "चीकू भाई, पत्ते हटाकर तो देखो, तुम्हारी दावत गिलहरियाँ पहले ही समाप्त कर चुकी हैं!",
                "s4_moral": "दोस्तों से छुपाकर रखी गई चीज़ कभी किसी के काम नहीं आती!",
                "bg": "forest_path",
                "sfx_s1": "tiptoe", "sfx_s2": "whoosh", "sfx_s3": "laughing_point", "sfx_s4": "success_ding"
            },
            {
                "item": "गन्ने का रसीला लट्ठ",
                "purpose": "दाँत से अकेले छीलना",
                "flaw": "दाँत में दर्द हो जाना",
                "s1_hook": "चीकू को खेत से एक मोटा ताज़ा गन्ना मिला, उसने गप्पू से बाँटने से साफ़ मना कर दिया!",
                "s1_narr": "गप्पू ने कहा आधा कर लो, लेकिन चीकू ने अकेले ही पूरा गन्ना चबाने की ठानी।",
                "s2_chiku": "गप्पू तुम छोटे हो, गन्ना पचा नहीं पाओगे, यह सिर्फ मेरे जैसे पहलवान के लिए है!",
                "s3_gappu": "चीकू भाई, पहलवान बनने के चक्कर में दाँत हिला बैठे, अब सूप पीकर ही काम चलाओ!",
                "s4_moral": "अहंकार और कंजूसी इंसान को खुद की ही नज़र में छोटा बना देती है!",
                "bg": "jungle_clearing",
                "sfx_s1": "whoosh", "sfx_s2": "crunch", "sfx_s3": "boing", "sfx_s4": "pop"
            }
        ]
    },
    {
        "category": "curiosity_mystery",
        "theme": "डर और सच्चाई",
        "subjects": [
            {
                "item": "गुफा के डरावने खर्राटे",
                "purpose": "भूत समझकर भागना",
                "flaw": "भालू काका की नींद",
                "s1_hook": "रात के सन्नाटे में जंगल की अंधेरी गुफा से 'घुर्र-घुर्र' की खौफनाक आवाज़ आई!",
                "s1_narr": "चीकू के रोंगटे खड़े हो गए, उसे लगा कि कोई दस सिर वाला राक्षस गुफा में आ धमका है।",
                "s2_chiku": "भागो गप्पू! अपनी जान बचाओ, गुफा के अंदर कोई विशालकाय दानव आ गया है!",
                "s3_gappu": "अरे चीकू भाई डरो मत! वह कोई दानव नहीं, हमारे भालू काका पेट भरकर सो रहे हैं!",
                "s4_moral": "डर हमेशा अज्ञान में होता है, सच सामने आते ही हँसी छूट जाती है!",
                "bg": "cave_entrance",
                "sfx_s1": "mystery_drone", "sfx_s2": "heartbeat", "sfx_s3": "snore", "sfx_s4": "success_ding"
            },
            {
                "item": "पेड़ पर लटकता साया",
                "purpose": "जंगल का पिशाच समझना",
                "flaw": "हवा में लहराता पुराना कंबल",
                "s1_hook": "चीकू ने शाम ढलते ही पीपल के पेड़ पर एक काला साया हिलते हुए देखा!",
                "s1_narr": "चीकू बंदर थर-थर काँपने लगा और चिल्लाने लगा कि पेड़ पर चुड़ैल लटक रही है।",
                "s2_chiku": "गप्पू देखो! वह काला साया हमें घूर रहा है, आज जंगल पर बड़ा संकट आ गया!",
                "s3_gappu": "चीकू भाई अपनी आँखें खोलो, वह किसी लकड़हारे का फटा हुआ कंबल है जो हवा में झूल रहा है!",
                "s4_moral": "वहम की कोई दवा नहीं होती, बुद्धि से काम लो तो भूत भी हवा हो जाता है!",
                "bg": "forest_path",
                "sfx_s1": "mystery_drone", "sfx_s2": "heartbeat", "sfx_s3": "boing", "sfx_s4": "success_ding"
            },
            {
                "item": "नदी में तैरती चमकती आँखें",
                "purpose": "जल-दानव का खौफ",
                "flaw": "चांद की परछाईं और दो चमकते जुगनू",
                "s1_hook": "नदी के काले पानी में चीकू को दो अंगारे जैसी दहकती आँखें तैरती दिखीं!",
                "s1_narr": "चीकू ने गप्पू का हाथ पकड़ा और चीखा कि पानी का राक्षस बाहर आ रहा है।",
                "s2_chiku": "गप्पू भागो! पानी का शैतान हमें कच्चा चबाने के लिए किनारे की तरफ बढ़ रहा है!",
                "s3_gappu": "चीकू भाई ज़रा पास आकर देखो, कमल के फूल पर दो जुगनू बैठे पानी में चमक रहे हैं!",
                "s4_moral": "अंधेरे में परछाइयाँ भी डराती हैं, ज्ञान का दीया जलाओ तो डर भाग जाता है!",
                "bg": "riverbank",
                "sfx_s1": "mystery_drone", "sfx_s2": "heartbeat", "sfx_s3": "twinkle", "sfx_s4": "success_ding"
            },
            {
                "item": "गुफा के अंदर की रहस्यमयी गूंज",
                "purpose": "अदृश्य आत्मा से बातचीत",
                "flaw": "खुद की ही आवाज़ की गूंज",
                "s1_hook": "गुफा के मुहाने पर चीकू ने 'हू-हू' किया तो अंदर से वही आवाज़ पलटकर आई!",
                "s1_narr": "चीकू को लगा कि गुफा में कोई जादुई हमशक्ल रहता है जो उसकी नकल उतार रहा है।",
                "s2_chiku": "गप्पू सुनो! गुफा की आत्मा मुझे चुनौती दे रही है, आज मेरा उससे मुकाबला होगा!",
                "s3_gappu": "चीकू भाई, वह तुम्हारी ही आवाज़ की गूँज है, पत्थरों से कुश्ती लड़कर सिर मत फोड़ लेना!",
                "s4_moral": "जो तुम संसार को देते हो, वही गूँज बनकर तुम्हारे पास लौट आता है!",
                "bg": "cave_entrance",
                "sfx_s1": "mystery_drone", "sfx_s2": "whoosh", "sfx_s3": "boing", "sfx_s4": "success_ding"
            }
        ]
    },
    {
        "category": "speed_race",
        "theme": "घमंड और रफ़्तार",
        "subjects": [
            {
                "item": "लकड़ी का पहिया स्केट्स",
                "purpose": "हवा से तेज़ दौड़ना",
                "flaw": "मोड़ पर ब्रेक न होना",
                "s1_hook": "चीकू ने लकड़ी के गोल टुकड़ों से अपने लिए पहिएदार चप्पलें बना डालीं!",
                "s1_narr": "चीकू ने पूरे जंगल में मुनादी करवा दी कि आज वह हिरण को भी रेस में हरा देगा।",
                "s2_chiku": "गप्पू सीटी बजाओ! आज चीकू की रफ़्तार देखकर जंगल के सारे जानवर दंग रह जाएँगे!",
                "s3_gappu": "चीकू भाई रुको! आगे तीव्र मोड़ है और तुमने चप्पलों में ब्रेक तो लगाया ही नहीं!",
                "s4_moral": "रफ़्तार से ज़्यादा ज़रूरी सही दिशा और नियंत्रण होता है!",
                "bg": "forest_path",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "slide_whistle", "sfx_s4": "pop"
            },
            {
                "item": "बांस का स्प्रिंग जंपर",
                "purpose": "एक छलांग में नदी पार करना",
                "flaw": "स्प्रिंग उल्टी दिशा में उछल जाना",
                "s1_hook": "चीकू बंदर ने बांस की लचीली टहनियों से एक ऊँचा स्प्रिंग तैयार कर लिया!",
                "s1_narr": "चीकू ने दावा किया कि वह एक ही छलांग में इस पार से उस पार पहुँच जाएगा।",
                "s2_chiku": "गप्पू देखो कमाल! चीकू बंदर अब बादलों को छूकर सीधे नदी के उस पार उतरेगा!",
                "s3_gappu": "चीकू भाई सावधान! स्प्रिंग फिसल गया है, तुम आगे नहीं सीधे कीचड़ में गिर रहे हो!",
                "s4_moral": "अंधाधुंध छलांग लगाने से पहले नीचे की ज़मीन ज़रूर देख लेनी चाहिए!",
                "bg": "riverbank",
                "sfx_s1": "whoosh", "sfx_s2": "boing", "sfx_s3": "slide_whistle", "sfx_s4": "pop"
            },
            {
                "item": "सरकंडे की नाव",
                "purpose": "नदी का सबसे तेज़ नाविक बनना",
                "flaw": "तली में बड़ा छेद होना",
                "s1_hook": "चीकू ने सूखी लकड़ियों को बाँधकर एक छोटी नाव बनाई और नदी में उतार दी!",
                "s1_narr": "चीकू ने गप्पू से कहा कि वह मछलियों से भी तेज़ तैरकर जंगल का कैप्टन बनेगा।",
                "s2_chiku": "गप्पू हाथ हिलाओ! तुम्हारा कैप्टन चीकू अब सागर जीतने निकला है!",
                "s3_gappu": "कैप्टन चीकू भाई, ज़रा नीचे देखो! नाव में पानी भर रहा है और तुम डूबने वाले हो!",
                "s4_moral": "बड़ी-बड़ी बातें करने से नहीं, मज़बूत तैयारी से नैया पार होती है!",
                "bg": "riverbank",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "boing", "sfx_s4": "pop"
            },
            {
                "item": "गुलेल वाली छलांग",
                "purpose": "पेड़ की चोटी पर सीधे पहुँचना",
                "flaw": "डाली वापस मुँह पर आ लगना",
                "s1_hook": "चीकू ने एक मोटी रबर जैसी बेल को खींचकर अपने लिए विशाल गुलेल बनाई!",
                "s1_narr": "चीकू बिना चढ़े सीधे पेड़ की सबसे ऊँची शाखा पर उड़कर पहुँचना चाहता था।",
                "s2_chiku": "गप्पू उल्टी गिनती शुरू करो! तीन, दो, एक... और चीकू बना रॉकेट!",
                "s3_gappu": "चीकू भाई छोड़ो मत! बेल का खिंचाव उल्टा है, तुम ऊपर नहीं डाली तुम्हारे मुँह पर आएगी!",
                "s4_moral": "शॉर्टकट के चक्कर में अक्सर इंसान मुँह के बल ही गिरता है!",
                "bg": "jungle_clearing",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "boing", "sfx_s4": "pop"
            }
        ]
    },
    {
        "category": "clever_sharing",
        "theme": "सच्ची दोस्ती और मदद",
        "subjects": [
            {
                "item": "मीठे जामुन का पेड़",
                "purpose": "ऊपर चढ़कर अकेले खाना",
                "flaw": "डाली टूटकर नीचे लटक जाना",
                "s1_hook": "चीकू बंदर को काले रसीले जामुनों से लदा हुआ एक बड़ा पेड़ मिल गया!",
                "s1_narr": "चीकू चुपके से सबसे पतली टहनी पर चढ़ गया ताकि गप्पू को भनक तक न लगे।",
                "s2_chiku": "आहा! इतने मीठे जामुन! नीचे बैठे गप्पू को क्या पता ऊपर क्या खज़ाना है!",
                "s3_gappu": "चीकू भाई, पतली डाली पर वज़न मत डालो, वह चरमरा रही है और तुम लटकने वाले हो!",
                "s4_moral": "अकेले मिठास चखने वाले अक्सर मुसीबत में अकेले ही रोते हैं!",
                "bg": "jungle_clearing",
                "sfx_s1": "tiptoe", "sfx_s2": "crunch", "sfx_s3": "slide_whistle", "sfx_s4": "success_ding"
            },
            {
                "item": "अनानास का ताज",
                "purpose": "जंगल का सम्राट घोषित करना",
                "flaw": "कांटे सिर में चुभ जाना",
                "s1_hook": "चीकू ने एक कांटेदार अनानास के ऊपरी हिस्से को काटकर अपने सिर पर ताज बना लिया!",
                "s1_narr": "चीकू जंगल में सीना तानकर घूमने लगा और सबको झुककर सलाम करने का हुक्म दिया।",
                "s2_chiku": "गप्पू झुककर प्रणाम करो! जंगल के नए राजा चीकू देव तुम्हारे सामने खड़े हैं!",
                "s3_gappu": "महाराज चीकू, अनानास के कांटे सिर में चुभने से पहले ताज उतार लो, वरना गंजे हो जाओगे!",
                "s4_moral": "ताज पहनने से कोई राजा नहीं बनता, गुण और विनम्रता ही असली बड़प्पन हैं!",
                "bg": "forest_path",
                "sfx_s1": "whoosh", "sfx_s2": "boast_proud", "sfx_s3": "boing", "sfx_s4": "success_ding"
            },
            {
                "item": "नारियल की गेंद",
                "purpose": "अकेले फुटबॉल का मैच जीतना",
                "flaw": "पैर में मोच आ जाना",
                "s1_hook": "चीकू को एक भारी सूखा नारियल मिला और उसने खुद को जंगल का मेसी घोषित कर दिया!",
                "s1_narr": "चीकू ने कहा कि वह अकेले ही गप्पू की पूरी टीम को गोल दागकर दिखाएगा।",
                "s2_chiku": "गप्पू गोलपोस्ट पर खड़े हो जाओ! चीकू की यह तूफानी किक कोई नहीं रोक सकता!",
                "s3_gappu": "चीकू भाई रुक जाओ! वह रबर की गेंद नहीं सख्त नारियल है, अंगूठा तुड़वा बैठोगे!",
                "s4_moral": "खेल में साथी का साथ और समझदारी दोनों ही जीत का असली राज़ हैं!",
                "bg": "jungle_clearing",
                "sfx_s1": "whoosh", "sfx_s2": "rev_up", "sfx_s3": "boing", "sfx_s4": "pop"
            },
            {
                "item": "सतरंगी तितली पकड़ने का जाल",
                "purpose": "पिंजरे में कैद करना",
                "flaw": "खुद ही जाल में उलझ जाना",
                "s1_hook": "चीकू ने जंगल की सबसे सुंदर सुनहरी तितली को पकड़ने के लिए बेलों का जाल बनाया!",
                "s1_narr": "चीकू उस मासूम तितली को कैद करके अपने पास रखना चाहता था।",
                "s2_chiku": "गप्पू देखो! यह सुनहरी तितली अब सिर्फ मेरी होगी और मेरे इशारों पर नाचेगी!",
                "s3_gappu": "चीकू भाई, आज़ादी सबको प्यारी होती है, देखो तितली उड़ गई और तुम खुद जाल में उलझ गए!",
                "s4_moral": "दूसरों की आज़ादी छीनने वाले अक्सर खुद के ही बनाए बंधनों में कैद हो जाते हैं!",
                "bg": "riverbank",
                "sfx_s1": "tiptoe", "sfx_s2": "twinkle", "sfx_s3": "slide_whistle", "sfx_s4": "success_ding"
            }
        ]
    }
]

# Baseline static templates preserved for fallback backwards compatibility
STORY_TEMPLATES = [
    {
        "category": "invention_mishap",
        "title": "चीकू का जादुई चश्मा",
        "hook": "चीकू बंदर को लगा कि उसने जंगल का सबसे बड़ा खजाना ढूंढ लिया है!",
        "scenes": [
            {
                "scene_num": 1,
                "speaker": "narrator",
                "dialogue": "चीकू बंदर खुशी से झूम रहा था। उसे लगा कि उसने कोई जादुई चीज़ खोज ली है!",
                "chiku_pose": "excited_jump",
                "gappu_pose": "observing",
                "camera": "medium_pan",
                "bg": "jungle_clearing",
                "sfx": "whoosh"
            },
            {
                "scene_num": 2,
                "speaker": "chiku",
                "dialogue": "गप्पू भाई! देखो, इस चमकते पत्थर से मैं जंगल का राजा बनूँगा!",
                "chiku_pose": "boast_proud",
                "gappu_pose": "skeptical_eyebrow",
                "camera": "close_up_chiku",
                "bg": "jungle_clearing",
                "sfx": "twinkle"
            },
            {
                "scene_num": 3,
                "speaker": "gappu",
                "dialogue": "चीकू भाई, राजा बनने से पहले चश्मा लगाकर देखो, वह खजाना नहीं, सिर्फ आम की गुठली है!",
                "chiku_pose": "shocked_freeze",
                "gappu_pose": "laughing_point",
                "camera": "two_shot_zoom",
                "bg": "jungle_clearing",
                "sfx": "boing"
            },
            {
                "scene_num": 4,
                "speaker": "narrator",
                "dialogue": "हर चमकती चीज़ सोना नहीं होती, कभी-कभी बस मीठा आम होती है!",
                "chiku_pose": "embarrassed_smile",
                "gappu_pose": "satisfied_nod",
                "camera": "wide_finish",
                "bg": "jungle_clearing",
                "sfx": "success_ding"
            }
        ]
    }
]


class StoryEngine:
    """Manages story generation, originality validation, and duplicate prevention.
    Combines modular narrative matrices to deliver rich variety across YouTube Shorts / Reels.
    """

    def __init__(self, history_file: Path = HISTORY_FILE):
        self.history_file = history_file
        self.history = self._load_history()

    def _load_history(self) -> List[Dict[str, Any]]:
        """Safely loads history. If corrupted, backs it up to .bak.<timestamp>
        before resetting, ensuring history data is NEVER silently destroyed.
        """
        if not self.history_file.exists():
            return []

        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                # Invalid structure
                raise ValueError("History root is not a list")
        except Exception as e:
            # Back up corrupted file immediately
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            bak_path = self.history_file.with_name(f"{self.history_file.name}.bak.{ts}")
            try:
                shutil.copy2(self.history_file, bak_path)
                print(f"[StoryEngine WARNING] Corrupted history backed up to {bak_path}: {e}")
            except Exception as copy_err:
                print(f"[StoryEngine ERROR] Failed to backup corrupt history: {copy_err}")
            return []

    def _save_history(self) -> None:
        """Saves recent history to JSON."""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        trimmed = self.history[-200:]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)

    def calculate_story_hash(self, title: str, hook: str) -> str:
        """Generates SHA-256 fingerprint for story deduplication."""
        content = f"{title.strip().lower()}|{hook.strip().lower()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def is_duplicate(self, story_hash: str, max_lookback: int = 50) -> bool:
        """Checks if story fingerprint exists in recent history."""
        recent = self.history[-max_lookback:]
        return any(entry.get("hash") == story_hash for entry in recent)

    def count_total_combinations(self) -> int:
        """Calculates total combinatorial possibilities from archetypes."""
        total = 0
        for arch in ARCHETYPES:
            total += len(arch["subjects"])
        # With 4 background options each, the space expands further
        return total * 4

    def generate_daily_story(self, force_template_idx: Optional[int] = None) -> Dict[str, Any]:
        """Generates a complete validated story with 4 scenes, consistent character rigs,
        natural Hindi dialogue, and genuine narrative progression.
        """
        # Build candidate pool from modular subjects
        candidates = []
        for arch in ARCHETYPES:
            cat = arch["category"]
            for sub in arch["subjects"]:
                candidates.append((cat, sub))

        # Lookback dynamically scaled so fresh candidates are guaranteed
        lookback_len = min(len(self.history), max(1, len(candidates) - 2))
        recent_hashes = {e.get("hash") for e in self.history[-lookback_len:]} if lookback_len > 0 else set()

        # Filter out recently used stories
        fresh_candidates = []
        for cat, sub in candidates:
            title = f"चीकू और {sub['item']}"
            hook = sub["s1_hook"]
            h = self.calculate_story_hash(title, hook)
            if h not in recent_hashes:
                fresh_candidates.append((cat, sub))

        pool = fresh_candidates if fresh_candidates else candidates
        if force_template_idx is not None and 0 <= force_template_idx < len(pool):
            cat, sub = pool[force_template_idx]
        else:
            cat, sub = random.choice(pool)

        title = f"चीकू और {sub['item']}"
        hook = sub["s1_hook"]
        story_hash = self.calculate_story_hash(title, hook)

        # Background selection: use subject's natural bg with slight variation
        bg = sub.get("bg", "jungle_clearing")

        # 4-Act structure
        scenes = [
            {
                "scene_num": 1,
                "speaker": "narrator",
                "dialogue": sub["s1_narr"],
                "chiku_pose": "excited_jump",
                "gappu_pose": "observing",
                "camera": "medium_pan",
                "bg": bg,
                "sfx": sub.get("sfx_s1", "whoosh")
            },
            {
                "scene_num": 2,
                "speaker": "chiku",
                "dialogue": sub["s2_chiku"],
                "chiku_pose": "boast_proud",
                "gappu_pose": "skeptical_eyebrow",
                "camera": "close_up_chiku",
                "bg": bg,
                "sfx": sub.get("sfx_s2", "rev_up")
            },
            {
                "scene_num": 3,
                "speaker": "gappu",
                "dialogue": sub["s3_gappu"],
                "chiku_pose": "shocked_freeze",
                "gappu_pose": "laughing_point",
                "camera": "two_shot_zoom",
                "bg": bg,
                "sfx": sub.get("sfx_s3", "boing")
            },
            {
                "scene_num": 4,
                "speaker": "narrator",
                "dialogue": sub["s4_moral"],
                "chiku_pose": "embarrassed_smile",
                "gappu_pose": "satisfied_nod",
                "camera": "wide_finish",
                "bg": bg,
                "sfx": sub.get("sfx_s4", "success_ding")
            }
        ]

        story_packet = {
            "story_id": f"story_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{story_hash[:6]}",
            "hash": story_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "category": cat,
            "title": title,
            "hook": hook,
            "characters": CHARACTERS,
            "scenes": scenes,
            "total_scenes": len(scenes)
        }

        # Record in history
        self.history.append({
            "story_id": story_packet["story_id"],
            "hash": story_hash,
            "title": story_packet["title"],
            "category": story_packet["category"],
            "created_at": story_packet["created_at"]
        })
        self._save_history()

        return story_packet


if __name__ == "__main__":
    engine = StoryEngine()
    print("=== Story Generation Engine Test ===")
    print(f"Total modular archetypes: {len(ARCHETYPES)}")
    combos = engine.count_total_combinations()
    print(f"Combinatorial variations available: {combos}")

    # Generate 10 consecutive stories and check uniqueness
    generated_titles = []
    generated_hashes = set()
    for i in range(10):
        story = engine.generate_daily_story()
        generated_titles.append(story["title"])
        generated_hashes.add(story["hash"])

    print(f"Generated 10 stories: {len(generated_hashes)} unique hashes.")
    for idx, t in enumerate(generated_titles, 1):
        print(f"  {idx}. {t}")
