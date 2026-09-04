################################################
"""Dashboard local de monitoramento integrado ao Mutant360.

Esta versão altera somente a apresentação da aplicação. As consultas,
campanhas, filtros e regras de autenticação continuam centralizadas em
``mutant_api.py``.
"""

from __future__ import annotations

import html
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from io import BytesIO
from textwrap import dedent
from typing import Any

import pandas as pd
import streamlit as st

from mutant_api import (
    BRASILIA_TZ,
    MutantApiError,
    MutantClient,
    UNITS,
    build_hourly_queue_flow,
    calculate_agent_tma,
    count_previous_day_closed,
    format_seconds,
    parse_api_datetime,
    queue_label,
    safe_int,
    summarize_analytic,
)


st.set_page_config(
    page_title="Sistema de Monitoria",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


UNIT_SHORT_NAMES = {
    "BRASILIA": "BSB",
    "COELBA": "Coelba",
    "PERNAMBUCO": "Pernambuco",
    "ELEKTRO": "Elektro",
    "COSERN": "Cosern",
}

UNIT_ICONS = {
    "BRASILIA": "🏙️",
    "COELBA": "💃🏾",
    "PERNAMBUCO": "⛱️",
    "ELEKTRO": "⚡",
    "COSERN": "☀️",
}

# Metas usadas no dashboard publicado: HC planejado por distribuidora
# multiplicado pela referência individual de 48 atendimentos por dia.
DAILY_PRODUCTIVITY_PER_HC = 48
UNIT_PLANNED_HEADCOUNT = {
    "BRASILIA": 7,
    "COELBA": 18,
    "PERNAMBUCO": 17,
    "ELEKTRO": 10,
    "COSERN": 14,
}
GENERAL_DAILY_PRODUCTIVITY_GOAL = (
    sum(UNIT_PLANNED_HEADCOUNT.values()) * DAILY_PRODUCTIVITY_PER_HC
)

# Intervalo único de atualização automática de todas as informações.
DASHBOARD_AUTO_REFRESH_SECONDS = 10 * 60
AUTO_REFRESH_TOLERANCE_SECONDS = 5
PAUSE_AUTO_REFRESH_SECONDS = DASHBOARD_AUTO_REFRESH_SECONDS

TME_DISTRIBUTORS = ("BSB", "Coelba", "Pernambuco", "Elektro", "Cosern")
TME_DISTRIBUTOR_BY_CODE = {
    "BRASILIA": "BSB",
    "COELBA": "Coelba",
    "PERNAMBUCO": "Pernambuco",
    "ELEKTRO": "Elektro",
    "COSERN": "Cosern",
}
TME_QUEUE_LIMITS = {
    "LN-TT": "00:30:00",
    "Principal": "00:30:00",
}


# Identificadores anonimizados da relação de colaboradores Logos enviada.
# O mesmo conjunto protegido é utilizado no dashboard publicado no GPT Site.
LOGOS_ROSTER_HASHES = frozenset(
    {
    "01436aa0010c2ced89b1a71ce7f834578866f13c82ad7d57cc972241887041ea",
    "016ef783b432cafd4f72faf752f1e906e1b0a04a789a05aac573110710940a7b",
    "079138510d93e95e2d75588efa26e1982b82cd4d5acc2a5b13f1600a14e9de04",
    "07f177337e1bc7e922aca5566d594b292469f154152335f08ec7794eabc8b55f",
    "085236bf8bc6811340143293a70e0b091cba25b68ac9b36718004583e14be2a9",
    "0a5cdc5b673c82123bdb02e2e7973d0f8e03c6cc5dfbee529cf0f65135236279",
    "0bdb4e13054582e23774e75d8e4720d3ffdb049f79d6d8a3df8c795e73f1ed4e",
    "0e45cd4553fdfad0aab0c27ddad0551a0e14ade1da973dd8dce9c18accd7407d",
    "114330fdb47db3483f1b5f806fd6b696fccf52807804d72aade7f1dd85e91a00",
    "12ff643a45b0e6beaefe828005c5ac447e589e1f873b46d059e5c8b2f77f8763",
    "1340d09430baefd1e64d3dc1827444f8a73765baded748ac6fff250e8773916b",
    "153e6e335b7ed3b0decf924f68d855ad1f6816e2f2574c67bed8e6954e63fe6d",
    "1549607ff6adebfd1065527b446f012505f3c9c6733905e91ec92596cc1fb6bb",
    "163b733a4f7c84201d66ab68eb5b8dfc06b2a7e2be05fe7ebd1c08293908aeee",
    "168db186d301e59c1b25a775b9e85874d9ab96356586b7f42956f6eed8396873",
    "18e7bdeba0505f91578615e3eb72b351c7ccc3df3e9cc5204f26033920cfa444",
    "18fc030ba531babffb91ea2866e57bb179e8985386e129b00319d6995ddda36c",
    "1c02148a6eefa818d3aad0c591a6cc36c02bfbea51cf50860d0ea2fda4098145",
    "1f0e132e70dddfb8e5bfb10b45f2797ba1b69950fd4fe343b902d13b7a2b45d2",
    "23b17c1d38af73a5b725655142a0fdade6a83402e328fa95a466e3acc591c64f",
    "29c5cde9ceea6dc2e1ca3afd0fcf36cc047f323618584056a956833d2bf6b4b7",
    "29e3976b8c3525dc3221b6a22f9b2014865f96d478f34686901fd2a344b6f350",
    "2a244a4165ad5eb706f30624c6f0449787d319be87c8a2842c0a53534026d772",
    "2a34eeeff2d9b1c36b953ab6ed74721c00c3386c6026d4958236827276e82a68",
    "2c265b704abff93cb8860bf0b17d57409ea7c2485f2d972f75fcf843445df2c1",
    "2d0e6656009fb9a19028f2bdec475c4f22b0d9e50a74b7c85d883a47f18c6127",
    "2e11b7d02b194457e8d73bf59e0d1eda646ebde06914bcca07d80489ae85ce20",
    "2edf175e5769a00e33f0fd9f4871f3650231998aad2a1365d9fd4ed7ab163063",
    "30dd9f6d154605c449e2a4c955a8cfaa5127b7937d3e45ad361e4ac2bd313cd5",
    "30ff35a98b7ae0f6114feb9e5b2c2094c8815f7387c42f36ee0fba28bb6bc08d",
    "33b65d60770fd4f5f9042bf5c0b39e043e01b881da8448472d7a59abb91226da",
    "3358957b9e371dc454d52e7723f0d3337af8b42e683c718d094db41eb6dc4f7f",
    "353d1777c020667b88a7579dff38cb5cb279cbc0967bb6549cdfd324d395df8e",
    "365e69a0591c52416c7f0b0e03e35fd658be7bc686a86ff0e5e43606873cbdc8",
    "37dcb0c244333d6e4611fe682d09cc4beb9c0ca0db62a76826fd89237ae13833",
    "38c90f0d8b25313972b0c789bdc2f2d122d041aecc66721ed0d0527fdf291ffd",
    "3a827498231a86bf33a3963f4da91afe812c2766a624a27147722a42175dbbcf",
    "3c48b03220153fb31c49f2b2889fff41678c9eb514ec44ca17042d90e7ffed61",
    "3c573f84425fa2f3a05cfe370f08618a0d7d7322c61dd09dbb29b94f9697fbb9",
    "3cc36c7163054bc902c7d081c8683bfc7362a066bb66ae148f454d598634a329",
    "3deb7f482b706d6b83a45b99a2ad2bea8dba3302e35db3223259d0162216721f",
    "3e5cdd43a8204183ce443a34a6f198abd4bd6a414ae674bb844afd4fc9fe1178",
    "3fb9a8398877b944bf329496af605aa92abdd258f549836413e34b8c904ca026",
    "40adaf30bb1d3139b425245fc3d2bde50271e111ac5f36627354daebde7280fa",
    "439ac62b56c38eacf6fba236e8aa8e2eab2881012573d621fa436a05514299af",
    "440cc72d65e638593c13d859bc5c00039bbb6574f50892c89c83ee0b5edd49f0",
    "4480f621ea8182143cfc731b135977a7d5b43ca2b278abe76a2fd612495d8a61",
    "45d18d097263b3c6f82ab4b32da84fee0b2cb986074708c6a387758a1130f6c1",
    "4a57946cb2eeec37c6548c7383bcc6526c86b17cdc508ffe91dae2f0c0aef656",
    "4b51ae63b69f4fc6c6f2d83453a1515c9d2eb06f600b74520c0f7da9342eac24",
    "4e6c73ead573c8e3778881af05b6829d39ff522f1588a268c15ddd282d2abe09",
    "4f8201bbc8c952f8489816e4221753058430b7342cc97eec99767680a4aca4ea",
    "5096a30cb41805b68a7001d86bbe712ed56ef60cd3378a7a50aa7b350642da71",
    "50cdb5eaa08a46ffca9bf6893b3ec675c9584cebbc302cdae062570aa9ee8936",
    "50cf47c4ac71cdb7151c367b002f4ed8addd05e53a671565887d273c7aa76f50",
    "52e652f88b45c0957142339768d0853a6a559ea526685fb48e5fa6bd92f181d4",
    "532a173f9dacb853f480352fcfab9f6de41c39fee99ccb2dff2fb09de76d0084",
    "540a52706371fe7aa2243539413392827a8d9b9a998df7c66a499e3b762b9129",
    "541d19910e91450b0900e14461124fbb8dcab4cc835075832e8c1c30c000a630",
    "5575f0632540bcaac4d7dce9e0bd01076ec276bd57de52c3aed3ab9bf71d91b6",
    "559b15eb33e103cd584bf548709f4249515a7ccbee3aa8d581fdb8451fe4db86",
    "572fb490a0c97308c72e0d7b8af89319d6e0fffc54eb8d2310d8179d5ee487d0",
    "57449cea0c88e5397b07bc65c1b7863bdd34aabb8a33a0833956ae9e27a3c6f2",
    "58ba31859849cb0bf3ccf606b0693a31b902b7d2aa5beaa2e034bf0b08b17c75",
    "59af2c2a3faaa4360876375695d45b48b9dc51eafe560288378aed6d46006078",
    "5cb2c707d082ecd51663f473a13648a0aacbca8141aa6497bb653ccf83989ca8",
    "6145e40e2d621b4be7ca53f5fa54fcc411dd21856069991a9c033d5edd3f1f0b",
    "64ee658c74074ced66d02ede306cd4ee6418a3c4fa34f90dbb9ef40e72170d50",
    "669f50f4e18df9262aa498a82d550399b57f576781695342136050f15a9861df",
    "68a673ee14b8cd15f06ef6caedc34958f41ca063e6049ec609cdfa33b3c7a498",
    "69a658cb739bfb2b69ab0a6dd05d1e51185bc4568f52b19be64193d8d2cee8b3",
    "6dffd226d2b6d5198a0528fb0c076bb5925efcff0a2e26e38d2712bce7fcfb4f",
    "6e5204b3953cf812afeca9f9829d1ddf83e79c55f7475a9017a830699323d087",
    "6f0e2f2ec6c472015e9544356ac7217a5278e7f768ff870fd15405c656676c1e",
    "704d013b58a363ba0a57d3353369d9a114a5d91a6448a52193c613298491bdf5",
    "73c9dd6468abeceba29c662bfbe9cfc749d63a3af18151eeec842a79f6704549",
    "7599051ad8db47ed0f9f8dc9b16d591cbf5ab62842af9d452c43ab138eb46970",
    "76f413be3181a5655d46a2d1373fe7b391d448684a615144344874120631350b",
    "77cf5a06b4db70f89d157ab19bbe5e9129568e17dfe06b6f9d84809439e66f84",
    "781b5ef8a18bb3b2bdd8801b583393ac5fe50da5d8d477672e5f3bce56dbc95f",
    "7a9fe4cdfec02754d62556838ab7067be0dcd0d6b28500a14631d085f268418c",
    "7b19e1f573f2a1308bf3332c2fcd1b290f008bf12e6b7e402c4e4320c5b59a09",
    "7c1d56489ec886722256238d5e30ca22dae9635a10d9c3a0d542c1b4808960ba",
    "7c6a663392107d0e5ae77f2d2b283b07b3083db2fe4ec44e98cd2fc83f35d275",
    "7e25d0edcb9d48ae3682c502ff8b4c9436e8348981272cd69a7a5775c76256d3",
    "82424822e1b1d7c5fca9ecd8118c7456e6ed4640ac32b543660c92333b3492c5",
    "83b791098d5c3c8b6df6301986fe288c0670f6faaa87cc91ea076121af44ae22",
    "83e9253e8f8de0446f05364e0cdd67536ec1866f65d6499a3bc9011de8b7d42c",
    "853c90ebd011825270f758c0d89fc45dc311a5c3e66496ec0a836e23c87b83fd",
    "87e214fc56dfbd4662070f742a9d86d094a27ee41ebc03b14229954780776994",
    "8818ab776664556b4f61cd389503467bb9a00cf723ae73c6bf821a1ba3182161",
    "8b129097ee008d6192054e609654166450f47664963881b3f5de5d00108ec7f9",
    "8bcc22032bc03c71d9972c32440884c96c902ec7efab8acde0fb0e554a52d9c7",
    "8e7a156c57530a39fc94a6fefb6e92fddf28753ff336b318407bda79fa6a70e1",
    "8e8ee995d478e5d8148601ca0a7e0f192cd281208e193eaa90b738162b20bf34",
    "90788e1e3f160159a31e3dc098484ca80742c5fb4bcfc9a0a3bdcaa79bbfa2bc",
    "95d5b2a664ab9729b89883989dd52a0093d97b0bd0a8ddc65cbb4859209686d8",
    "95d6c206b08148e4a0a7ac4977e83a0b03973d8a2880e3960d3af93da39a94c9",
    "95d8af09962ea89aac72f70b13840ccc589a294b38adb32c5f76e87c28a172f6",
    "980997b7fbc1636c0fde56f0c668ed75b12d2a0d9298bdae292e0d8a474bece7",
    "996e5f5f3122d5164f253befbe8de4f0e6cebd92cc5fb31bf45986c26ecdf493",
    "997c880d0d73d5fe10d20698c6bac13bb7e00effd2342fd5ff8c16ab201971db",
    "9b213822d200ecb438d4d116fa080c1c33f7dd53131636167825cd603bf5a11d",
    "9b9dccc862753f85fb197be74a95218b52efdec8ce7b1983bea776b75b2f44d7",
    "9c13958a982d69a81092c2615073eda31ac98a545ecb02f2aa0677bd0e125d40",
    "9f4ab82a1cbbe9a167b4a766c19f5f1db5d02d30bb03961610708a3487ae7573",
    "9f661e39fc9ad740af980e04b60fd788150349260481c74c72cfe8b32b9127b4",
    "a1262838d0205a23691d30fa6da1ae201fedc27c13ee6848d74a8d9cee4a841e",
    "a279669303c2aa8b42fb592518ace55cd7829718b062fb174a3ec6aaf10b678e",
    "a4bc4e201fc578ca7d64e907f27271d44a77625c00fb17582ee1f842a9229128",
    "a4f164af81a6f0b00bd6993f7000946e9773a4f9ae2a06ec10e66c5667e5e576",
    "a6f3b69ed9aa14dbcfb13f12a6d687d27b4ccd9129baf701d4724127e24d8cfc",
    "a72e7a42f688d4f5a232fcf65016398dd42bd63329564cdb3b4e02430476c045",
    "a8aa69a26805e80e1390075212e1e46871ee77f2e2417b733215f9d0c9c9cb33",
    "aaa706dfad089cbf42f17713e89f40ade6dbc03ff4a55c0e0376e52db3ec49df",
    "aaf7605007fc404f8e62e2a17684f03b59300bfa29795d9bc367fbf0f8bc61ae",
    "ac436088a64ce4dbde4f0de3c776cc080aee1724191c1ad0c1f3c22c4725bc31",
    "aff5b839d9846917517f7e7737f00772ae1b929fb47cee1577407928d9a39d88",
    "b08c3f5adf8e2677703161c219e1f3e3b08492fe025c5bced28944754020609b",
    "b3156bc3eca34691c5019c9840db0bdc49c4c2a5eaa34cb1cb3e3b95c3503c89",
    "b529a8102deec3e6eacfff2eed309f2791ba08000b243f2ca0d1c2e61753f933",
    "b55b8ad13d3717bbd59ca7a1f2e44e7bc00d7c2d01f989630582e90276d7607c",
    "b564aee73370f9b9d301ab8e58df6503bdfe5c11230ee75d54f77f7692997252",
    "b574252d3dc4ca7dc2321658ab1fbaa23b34b7b526056ebe91f523dcfb8075fd",
    "bbe6a098db8c7db877fd90539cfdf586979ee3c46356ede336230f204032e05c",
    "bbeb9434a3b98a32692c8e81ea15dd8cb67534b44b0defafe70b82bbd2bfd063",
    "bfb7f628fdb500eec2049b8dd0bbb725d10a552e4c4e18d8a9b338bc69597ba0",
    "c084e634dc1b728574da198cd2ca2beceb239791e15a554fc09c612fb49fc037",
    "c1da81f3d0acf7525a69d8a3873f45d9f174abfd6aacb378608552d83f0c1617",
    "c2747bf85600ddf125e38b96ba55603cd7a130589ad457e9fb38647d68cc00d6",
    "c27b3a6d923c117f68fe3c7edc9672219f4a69e9455222b42034d8db423bcaab",
    "c28f8d0fb131a3a7b135847efc6b6b6883f1a9793f676c9d0fb53ad990c8e2e6",
    "c2b3b3aab36a8c6efff214af8a8c2402178b77f527cd3a8ac102f9980b8dd4e0",
    "c558e1b9aad3aff4c1b70ae846be8014ad87f31c7ff73c70152934a60df6460c",
    "c57f4d6baccc252bd1d9fb4d475e9b92b28228e468b8c66f082e88009f4e7c9f",
    "c5d1a794bbd5362d0c57531a356fde2b87a38e86d20ccc75df498e4a918d3719",
    "c62b7e466d511ddaceffd582ba9acf3e695f1076fd4efc9641b328061bfd549f",
    "cac6150dd5017dd1698be7bbac8bdb83c143a18f2885c3e7941c78dc31dabcfd",
    "cb603bb1dafbe757a3f52b403886b7621e77ece251ac28d4441d12b9b305fadb",
    "cde38a46d0c3e97105520cc381c38cbb67815354f17ee1fc30495e04ccb57332",
    "cdeb6b6b0d79951ef893afc5d735bb1e74f3262034e99dab970682ba49bb414d",
    "ceeceb47c19520d0faff29149b2931b766b6055657054643c0cd3c74169268d7",
    "cfde9fb9b58b9249494863f168fc15047ffcb65a0b86573e34a372dfe4025b71",
    "d0912d5b4dc58e1e98a6aefca45c2e9b68e466f5b4a9823ef18dc9e15dd6c9a5",
    "d25a9f85ee2c746a5d9553722a0c408b1801b427defb863c04264e5485549509",
    "d26c62755f40359bdc1fe89e355155f5dbd347a6d9bbabb35a507b0419254de6",
    "d4d241d61998931175e7a3ab8ed4fce3c2fad8b611fe553e02d1ef06b6fd40e6",
    "d63cb882c2a0778094479a491417617be908a9de569b6c0102b4d80628e46de3",
    "d7737fba1254e4a693c1e845d59ede550249ce47f586eb0549f429bc7e0054d4",
    "d7cc9af3d3a1f75550211e06c3d8666bcd31437d0ba30fa4d2495ad66491c37c",
    "d7f331821ff87e582115a7f3fdb11fba8aca3161814d61ca29ae84502b4a6553",
    "d9de2d68081bf54342cd60876fdd9256983e88c0573665ec4b8252ae312e6041",
    "db5e4e9a4f0875417b3f0d78ea8b0cc4d0da953a594ae8db14ba43b33f53a91a",
    "dc65148dd1c7bf7183b1aabeb631c7c590f310dfe489100c928a568535efc35d",
    "de56dd749723e4bc1ade07e00b5137265bc24e25f4738d0d3289a8c2b0f30e45",
    "df1e8c645b275c91e4510a75cb670dcc1a2efa106bb779465986e0750d14fdde",
    "df771be6f0cea1c7608130d4a296ea609aa1374de5e0d6e3c569acab905127cd",
    "dfe721e345d356bf5ee8ff8f623754a5c33dd40ac08a9991036dcf623f1f8528",
    "e0d4afcc09bd3589f826ec148141b9d59419cf9154b4a07b7d6d3fff30b17601",
    "e1acce676303c98443e68cd4e34508bb2a00acbf23e1dd3e538aa77c163c0f68",
    "e28e6b07f3c4c6566569ccebc73fd31b4c2aba8221d8859ab0b5ac8b4bdb14ec",
    "e770e8dc793b4d4ed94d46ea6c3ab5e8b7d11ad3da1aa759e4404bbba0f709d0",
    "e93936d87546ea3ea5956f279b69adf353ae430c365f7a8228cd35769bc516d2",
    "eab5ec64bf1a2c5b7f5b1e0b4b252a54240d65a3ace6215f905460deb8ba5db8",
    "eb72df61c3c07be7d1e53ec783dcdba0c0b1f2f3bc833aa82f888362cb706d10",
    "eb730d2a62d0ac3b5cfb1bd08cad07a46bcd42c38bc115704ffd9f0dd770e67d",
    "ebf8b01629c604667449d66e17102a6c9dbed848cec26c17db51164bfe667652",
    "ece12d19830b92eaf80655eb42c8e669131379a012b669710a15f079b89c16f1",
    "ecf23b422c4a45424e75ced499b70182c7e34eadd4190a7bf53edca289821d38",
    "ed05cc2a9e7e7946a0887db07e1827211b568ea5a3183fda35509f71c9a0eeb2",
    "eeb4148d184a1baa080636e5928bf3bd060c59d694af095d960d4bc2a8e022fd",
    "f112d6636d4aa231b9c18cae3f903ee775ffe5b5cab48f81e98c00e866e2448b",
    "f2a7e79f803f344adb0efc1aa79f678f4c997fa84ddf5fb6aa1d720a2eb73302",
    "f3545a85ec0da5746acde22629a21023a4b7bbf7d5e16b31417ef74c5528b804",
    "f84ddce3ca45c488dcf5de3c0efb6b2c8b7c080b4bd73751f00219ee247efab0",
    "fb33a272170c6ce1661220ec0986095becaa1bbfb121454d2c5ac5412b076952",
    "fbada4fde7cec0eef11e41ecae2781fcc28131fcfc9d33f2aef21ec6313033af",
    "fd5d8f4a81dfb3e104b7697bde1bc710335d7c47a8cdef9e761d23ffb86e31e1",
    "fec81264b055f4c393fa03b4aea89e3fec2c69c6c0bb8b30b59308c8f4def0a5",
    }
)

LOGOS_IDENTIFIER_ALIASES = {
    "rafaella waleska souza pereira": "rafaela waleska souza pereira",
}

# Relação específica do monitoramento de pausas. Os identificadores do novo
# quadro foram protegidos por SHA-256 e associados à distribuidora de origem.
# Inclui colaboradores ATIVOS e em AVISO PRÉVIO; FÉRIAS e INSS ficam de fora.
PAUSE_ROSTER_UNIT_BY_HASH = {
    "01436aa0010c2ced89b1a71ce7f834578866f13c82ad7d57cc972241887041ea": "COSERN",
    "016ef783b432cafd4f72faf752f1e906e1b0a04a789a05aac573110710940a7b": "ELEKTRO",
    "07f177337e1bc7e922aca5566d594b292469f154152335f08ec7794eabc8b55f": "ELEKTRO",
    "085236bf8bc6811340143293a70e0b091cba25b68ac9b36718004583e14be2a9": "COSERN",
    "0a5cdc5b673c82123bdb02e2e7973d0f8e03c6cc5dfbee529cf0f65135236279": "BRASILIA",
    "0bdb4e13054582e23774e75d8e4720d3ffdb049f79d6d8a3df8c795e73f1ed4e": "COSERN",
    "12ff643a45b0e6beaefe828005c5ac447e589e1f873b46d059e5c8b2f77f8763": "PERNAMBUCO",
    "1340d09430baefd1e64d3dc1827444f8a73765baded748ac6fff250e8773916b": "COELBA",
    "153e6e335b7ed3b0decf924f68d855ad1f6816e2f2574c67bed8e6954e63fe6d": "ELEKTRO",
    "1549607ff6adebfd1065527b446f012505f3c9c6733905e91ec92596cc1fb6bb": "BRASILIA",
    "163b733a4f7c84201d66ab68eb5b8dfc06b2a7e2be05fe7ebd1c08293908aeee": "PERNAMBUCO",
    "168db186d301e59c1b25a775b9e85874d9ab96356586b7f42956f6eed8396873": "COELBA",
    "18e7bdeba0505f91578615e3eb72b351c7ccc3df3e9cc5204f26033920cfa444": "BRASILIA",
    "18fc030ba531babffb91ea2866e57bb179e8985386e129b00319d6995ddda36c": "PERNAMBUCO",
    "1f0e132e70dddfb8e5bfb10b45f2797ba1b69950fd4fe343b902d13b7a2b45d2": "PERNAMBUCO",
    "23b17c1d38af73a5b725655142a0fdade6a83402e328fa95a466e3acc591c64f": "ELEKTRO",
    "29c5cde9ceea6dc2e1ca3afd0fcf36cc047f323618584056a956833d2bf6b4b7": "COELBA",
    "2c265b704abff93cb8860bf0b17d57409ea7c2485f2d972f75fcf843445df2c1": "PERNAMBUCO",
    "2d0e6656009fb9a19028f2bdec475c4f22b0d9e50a74b7c85d883a47f18c6127": "PERNAMBUCO",
    "30dd9f6d154605c449e2a4c955a8cfaa5127b7937d3e45ad361e4ac2bd313cd5": "BRASILIA",
    "30ff35a98b7ae0f6114feb9e5b2c2094c8815f7387c42f36ee0fba28bb6bc08d": "COELBA",
    "353d1777c020667b88a7579dff38cb5cb279cbc0967bb6549cdfd324d395df8e": "ELEKTRO",
    "38c90f0d8b25313972b0c789bdc2f2d122d041aecc66721ed0d0527fdf291ffd": "ELEKTRO",
    "3a827498231a86bf33a3963f4da91afe812c2766a624a27147722a42175dbbcf": "COSERN",
    "3c573f84425fa2f3a05cfe370f08618a0d7d7322c61dd09dbb29b94f9697fbb9": "COSERN",
    "3deb7f482b706d6b83a45b99a2ad2bea8dba3302e35db3223259d0162216721f": "PERNAMBUCO",
    "3fb9a8398877b944bf329496af605aa92abdd258f549836413e34b8c904ca026": "PERNAMBUCO",
    "40adaf30bb1d3139b425245fc3d2bde50271e111ac5f36627354daebde7280fa": "COSERN",
    "440cc72d65e638593c13d859bc5c00039bbb6574f50892c89c83ee0b5edd49f0": "ELEKTRO",
    "4480f621ea8182143cfc731b135977a7d5b43ca2b278abe76a2fd612495d8a61": "COSERN",
    "44fef09c4bd36dd080c4ceb0dc8d3e5beab71f67ba497731cd9644e8023fde6c": "ELEKTRO",
    "45d18d097263b3c6f82ab4b32da84fee0b2cb986074708c6a387758a1130f6c1": "COSERN",
    "4a57946cb2eeec37c6548c7383bcc6526c86b17cdc508ffe91dae2f0c0aef656": "BRASILIA",
    "4a78555730f8481c615f3f57da14aaf57991075c31711d389a38b726b8191a9d": "ELEKTRO",
    "4b51ae63b69f4fc6c6f2d83453a1515c9d2eb06f600b74520c0f7da9342eac24": "COSERN",
    "4e6c73ead573c8e3778881af05b6829d39ff522f1588a268c15ddd282d2abe09": "ELEKTRO",
    "4f8201bbc8c952f8489816e4221753058430b7342cc97eec99767680a4aca4ea": "COSERN",
    "5096a30cb41805b68a7001d86bbe712ed56ef60cd3378a7a50aa7b350642da71": "PERNAMBUCO",
    "50cdb5eaa08a46ffca9bf6893b3ec675c9584cebbc302cdae062570aa9ee8936": "COSERN",
    "52e652f88b45c0957142339768d0853a6a559ea526685fb48e5fa6bd92f181d4": "COELBA",
    "532a173f9dacb853f480352fcfab9f6de41c39fee99ccb2dff2fb09de76d0084": "COELBA",
    "540a52706371fe7aa2243539413392827a8d9b9a998df7c66a499e3b762b9129": "COSERN",
    "541d19910e91450b0900e14461124fbb8dcab4cc835075832e8c1c30c000a630": "COELBA",
    "5575f0632540bcaac4d7dce9e0bd01076ec276bd57de52c3aed3ab9bf71d91b6": "PERNAMBUCO",
    "559b15eb33e103cd584bf548709f4249515a7ccbee3aa8d581fdb8451fe4db86": "PERNAMBUCO",
    "57449cea0c88e5397b07bc65c1b7863bdd34aabb8a33a0833956ae9e27a3c6f2": "COELBA",
    "58ba31859849cb0bf3ccf606b0693a31b902b7d2aa5beaa2e034bf0b08b17c75": "COELBA",
    "5cb2c707d082ecd51663f473a13648a0aacbca8141aa6497bb653ccf83989ca8": "PERNAMBUCO",
    "5d1dc93a86aec2d818c94318f2de4d31fdd14a93ca9a5853b2769284af9f31de": "ELEKTRO",
    "6145e40e2d621b4be7ca53f5fa54fcc411dd21856069991a9c033d5edd3f1f0b": "PERNAMBUCO",
    "64ee658c74074ced66d02ede306cd4ee6418a3c4fa34f90dbb9ef40e72170d50": "PERNAMBUCO",
    "669f50f4e18df9262aa498a82d550399b57f576781695342136050f15a9861df": "COELBA",
    "68a673ee14b8cd15f06ef6caedc34958f41ca063e6049ec609cdfa33b3c7a498": "PERNAMBUCO",
    "69a658cb739bfb2b69ab0a6dd05d1e51185bc4568f52b19be64193d8d2cee8b3": "BRASILIA",
    "6cf8332ea6d6d39a16d16af4f0ee2a2ed120f9b22d44f15773b0eb52b84cbccf": "PERNAMBUCO",
    "6d1b69d4c26ec50f99b179ffbfdb0a14b20660b599802418c9838c3b4de3628e": "PERNAMBUCO",
    "6e5204b3953cf812afeca9f9829d1ddf83e79c55f7475a9017a830699323d087": "COSERN",
    "6f0e2f2ec6c472015e9544356ac7217a5278e7f768ff870fd15405c656676c1e": "PERNAMBUCO",
    "704d013b58a363ba0a57d3353369d9a114a5d91a6448a52193c613298491bdf5": "ELEKTRO",
    "73c9dd6468abeceba29c662bfbe9cfc749d63a3af18151eeec842a79f6704549": "COSERN",
    "7599051ad8db47ed0f9f8dc9b16d591cbf5ab62842af9d452c43ab138eb46970": "COSERN",
    "76f413be3181a5655d46a2d1373fe7b391d448684a615144344874120631350b": "ELEKTRO",
    "77cf5a06b4db70f89d157ab19bbe5e9129568e17dfe06b6f9d84809439e66f84": "COSERN",
    "781b5ef8a18bb3b2bdd8801b583393ac5fe50da5d8d477672e5f3bce56dbc95f": "COSERN",
    "7a9fe4cdfec02754d62556838ab7067be0dcd0d6b28500a14631d085f268418c": "ELEKTRO",
    "7b19e1f573f2a1308bf3332c2fcd1b290f008bf12e6b7e402c4e4320c5b59a09": "COSERN",
    "7c6a663392107d0e5ae77f2d2b283b07b3083db2fe4ec44e98cd2fc83f35d275": "PERNAMBUCO",
    "82424822e1b1d7c5fca9ecd8118c7456e6ed4640ac32b543660c92333b3492c5": "PERNAMBUCO",
    "83b791098d5c3c8b6df6301986fe288c0670f6faaa87cc91ea076121af44ae22": "ELEKTRO",
    "83e9253e8f8de0446f05364e0cdd67536ec1866f65d6499a3bc9011de8b7d42c": "COSERN",
    "853c90ebd011825270f758c0d89fc45dc311a5c3e66496ec0a836e23c87b83fd": "COSERN",
    "87e214fc56dfbd4662070f742a9d86d094a27ee41ebc03b14229954780776994": "PERNAMBUCO",
    "8818ab776664556b4f61cd389503467bb9a00cf723ae73c6bf821a1ba3182161": "PERNAMBUCO",
    "8e7a156c57530a39fc94a6fefb6e92fddf28753ff336b318407bda79fa6a70e1": "ELEKTRO",
    "8e8ee995d478e5d8148601ca0a7e0f192cd281208e193eaa90b738162b20bf34": "PERNAMBUCO",
    "90788e1e3f160159a31e3dc098484ca80742c5fb4bcfc9a0a3bdcaa79bbfa2bc": "COSERN",
    "95d5b2a664ab9729b89883989dd52a0093d97b0bd0a8ddc65cbb4859209686d8": "COELBA",
    "95d6c206b08148e4a0a7ac4977e83a0b03973d8a2880e3960d3af93da39a94c9": "BRASILIA",
    "95d8af09962ea89aac72f70b13840ccc589a294b38adb32c5f76e87c28a172f6": "COELBA",
    "980997b7fbc1636c0fde56f0c668ed75b12d2a0d9298bdae292e0d8a474bece7": "COSERN",
    "996e5f5f3122d5164f253befbe8de4f0e6cebd92cc5fb31bf45986c26ecdf493": "COSERN",
    "997c880d0d73d5fe10d20698c6bac13bb7e00effd2342fd5ff8c16ab201971db": "COELBA",
    "9b9dccc862753f85fb197be74a95218b52efdec8ce7b1983bea776b75b2f44d7": "PERNAMBUCO",
    "9c13958a982d69a81092c2615073eda31ac98a545ecb02f2aa0677bd0e125d40": "COSERN",
    "a279669303c2aa8b42fb592518ace55cd7829718b062fb174a3ec6aaf10b678e": "COELBA",
    "a4bc4e201fc578ca7d64e907f27271d44a77625c00fb17582ee1f842a9229128": "BRASILIA",
    "a4f164af81a6f0b00bd6993f7000946e9773a4f9ae2a06ec10e66c5667e5e576": "ELEKTRO",
    "a6f3b69ed9aa14dbcfb13f12a6d687d27b4ccd9129baf701d4724127e24d8cfc": "COSERN",
    "a8aa69a26805e80e1390075212e1e46871ee77f2e2417b733215f9d0c9c9cb33": "ELEKTRO",
    "aaa706dfad089cbf42f17713e89f40ade6dbc03ff4a55c0e0376e52db3ec49df": "ELEKTRO",
    "aaf7605007fc404f8e62e2a17684f03b59300bfa29795d9bc367fbf0f8bc61ae": "PERNAMBUCO",
    "ac436088a64ce4dbde4f0de3c776cc080aee1724191c1ad0c1f3c22c4725bc31": "PERNAMBUCO",
    "aff5b839d9846917517f7e7737f00772ae1b929fb47cee1577407928d9a39d88": "COSERN",
    "b08c3f5adf8e2677703161c219e1f3e3b08492fe025c5bced28944754020609b": "COELBA",
    "b3156bc3eca34691c5019c9840db0bdc49c4c2a5eaa34cb1cb3e3b95c3503c89": "COELBA",
    "b529a8102deec3e6eacfff2eed309f2791ba08000b243f2ca0d1c2e61753f933": "COELBA",
    "b55b8ad13d3717bbd59ca7a1f2e44e7bc00d7c2d01f989630582e90276d7607c": "PERNAMBUCO",
    "b564aee73370f9b9d301ab8e58df6503bdfe5c11230ee75d54f77f7692997252": "PERNAMBUCO",
    "b574252d3dc4ca7dc2321658ab1fbaa23b34b7b526056ebe91f523dcfb8075fd": "PERNAMBUCO",
    "b8f7c87a1b02d97da729eb2e805c7753e168d874ffaef495da55399666bb559c": "ELEKTRO",
    "bbe6a098db8c7db877fd90539cfdf586979ee3c46356ede336230f204032e05c": "COELBA",
    "bbeb9434a3b98a32692c8e81ea15dd8cb67534b44b0defafe70b82bbd2bfd063": "PERNAMBUCO",
    "bfb7f628fdb500eec2049b8dd0bbb725d10a552e4c4e18d8a9b338bc69597ba0": "BRASILIA",
    "c084e634dc1b728574da198cd2ca2beceb239791e15a554fc09c612fb49fc037": "COSERN",
    "c1da81f3d0acf7525a69d8a3873f45d9f174abfd6aacb378608552d83f0c1617": "COSERN",
    "c2747bf85600ddf125e38b96ba55603cd7a130589ad457e9fb38647d68cc00d6": "COSERN",
    "c27b3a6d923c117f68fe3c7edc9672219f4a69e9455222b42034d8db423bcaab": "BRASILIA",
    "c28f8d0fb131a3a7b135847efc6b6b6883f1a9793f676c9d0fb53ad990c8e2e6": "BRASILIA",
    "c2b3b3aab36a8c6efff214af8a8c2402178b77f527cd3a8ac102f9980b8dd4e0": "PERNAMBUCO",
    "c558e1b9aad3aff4c1b70ae846be8014ad87f31c7ff73c70152934a60df6460c": "ELEKTRO",
    "c57f4d6baccc252bd1d9fb4d475e9b92b28228e468b8c66f082e88009f4e7c9f": "COSERN",
    "c5d1a794bbd5362d0c57531a356fde2b87a38e86d20ccc75df498e4a918d3719": "COELBA",
    "c62b7e466d511ddaceffd582ba9acf3e695f1076fd4efc9641b328061bfd549f": "COELBA",
    "cac6150dd5017dd1698be7bbac8bdb83c143a18f2885c3e7941c78dc31dabcfd": "BRASILIA",
    "cb603bb1dafbe757a3f52b403886b7621e77ece251ac28d4441d12b9b305fadb": "COSERN",
    "cde38a46d0c3e97105520cc381c38cbb67815354f17ee1fc30495e04ccb57332": "COSERN",
    "ceeceb47c19520d0faff29149b2931b766b6055657054643c0cd3c74169268d7": "COSERN",
    "cfde9fb9b58b9249494863f168fc15047ffcb65a0b86573e34a372dfe4025b71": "PERNAMBUCO",
    "d0912d5b4dc58e1e98a6aefca45c2e9b68e466f5b4a9823ef18dc9e15dd6c9a5": "PERNAMBUCO",
    "d25a9f85ee2c746a5d9553722a0c408b1801b427defb863c04264e5485549509": "ELEKTRO",
    "d26c62755f40359bdc1fe89e355155f5dbd347a6d9bbabb35a507b0419254de6": "COELBA",
    "d4d241d61998931175e7a3ab8ed4fce3c2fad8b611fe553e02d1ef06b6fd40e6": "ELEKTRO",
    "d63cb882c2a0778094479a491417617be908a9de569b6c0102b4d80628e46de3": "ELEKTRO",
    "d7737fba1254e4a693c1e845d59ede550249ce47f586eb0549f429bc7e0054d4": "PERNAMBUCO",
    "d7cc9af3d3a1f75550211e06c3d8666bcd31437d0ba30fa4d2495ad66491c37c": "COELBA",
    "d7f331821ff87e582115a7f3fdb11fba8aca3161814d61ca29ae84502b4a6553": "COELBA",
    "d9de2d68081bf54342cd60876fdd9256983e88c0573665ec4b8252ae312e6041": "ELEKTRO",
    "db5e4e9a4f0875417b3f0d78ea8b0cc4d0da953a594ae8db14ba43b33f53a91a": "COSERN",
    "dc65148dd1c7bf7183b1aabeb631c7c590f310dfe489100c928a568535efc35d": "PERNAMBUCO",
    "de56dd749723e4bc1ade07e00b5137265bc24e25f4738d0d3289a8c2b0f30e45": "COELBA",
    "df1e8c645b275c91e4510a75cb670dcc1a2efa106bb779465986e0750d14fdde": "PERNAMBUCO",
    "df771be6f0cea1c7608130d4a296ea609aa1374de5e0d6e3c569acab905127cd": "BRASILIA",
    "dfe721e345d356bf5ee8ff8f623754a5c33dd40ac08a9991036dcf623f1f8528": "BRASILIA",
    "e0d4afcc09bd3589f826ec148141b9d59419cf9154b4a07b7d6d3fff30b17601": "COELBA",
    "e1acce676303c98443e68cd4e34508bb2a00acbf23e1dd3e538aa77c163c0f68": "COELBA",
    "e28e6b07f3c4c6566569ccebc73fd31b4c2aba8221d8859ab0b5ac8b4bdb14ec": "PERNAMBUCO",
    "e93936d87546ea3ea5956f279b69adf353ae430c365f7a8228cd35769bc516d2": "ELEKTRO",
    "eab5ec64bf1a2c5b7f5b1e0b4b252a54240d65a3ace6215f905460deb8ba5db8": "COSERN",
    "eb72df61c3c07be7d1e53ec783dcdba0c0b1f2f3bc833aa82f888362cb706d10": "COSERN",
    "eb730d2a62d0ac3b5cfb1bd08cad07a46bcd42c38bc115704ffd9f0dd770e67d": "PERNAMBUCO",
    "ebf8b01629c604667449d66e17102a6c9dbed848cec26c17db51164bfe667652": "COELBA",
    "ece12d19830b92eaf80655eb42c8e669131379a012b669710a15f079b89c16f1": "ELEKTRO",
    "ecf23b422c4a45424e75ced499b70182c7e34eadd4190a7bf53edca289821d38": "ELEKTRO",
    "f112d6636d4aa231b9c18cae3f903ee775ffe5b5cab48f81e98c00e866e2448b": "ELEKTRO",
    "f3545a85ec0da5746acde22629a21023a4b7bbf7d5e16b31417ef74c5528b804": "PERNAMBUCO",
    "f84ddce3ca45c488dcf5de3c0efb6b2c8b7c080b4bd73751f00219ee247efab0": "COELBA",
    "fb33a272170c6ce1661220ec0986095becaa1bbfb121454d2c5ac5412b076952": "BRASILIA",
    "fbada4fde7cec0eef11e41ecae2781fcc28131fcfc9d33f2aef21ec6313033af": "COELBA",
    "fd5d8f4a81dfb3e104b7697bde1bc710335d7c47a8cdef9e761d23ffb86e31e1": "PERNAMBUCO",
}

PAUSE_RULES: dict[str, dict[str, Any]] = {
    "refeicao": {
        "label": "Refeição",
        "limit_seconds": 60 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: O(A) colaborador(a) "
            "{name} ({unit}) ultrapassou o tempo limite de 1h estabelecido "
            "para a pausa Refeição. Por favor, verificar a situação com o "
            "operador."
        ),
    },
    "saude": {
        "label": "Saúde",
        "limit_seconds": 20 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: Identificado excesso de "
            "tempo na pausa Saúde do(a) colaborador(a) {name} ({unit}) "
            "(limite de 20min). Por favor, alinhar com o operador para "
            "verificar se há necessidade de suporte médico adicional."
        ),
    },
    "particular": {
        "label": "Particular",
        "limit_seconds": 10 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: O(A) colaborador(a) "
            "{name} ({unit}) excedeu o limite regular de 10min para a pausa "
            "Particular. Solicita-se a verificação do status junto ao operador."
        ),
    },
    "emergencia brigada": {
        "label": "Emergência (Brigada)",
        "limit_seconds": 20 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: Registrado estouro no "
            "tempo de pausa Emergência (limite de 20min) para o(a) "
            "colaborador(a) {name} ({unit}). Por favor, acompanhar para "
            "validar a situação com a Brigada."
        ),
    },
    "feedback": {
        "label": "Feedback",
        "limit_seconds": 20 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: O tempo estipulado para a "
            "pausa Feedback (20min) foi ultrapassado pelo(a) colaborador(a) "
            "{name} ({unit}). Por favor, certificar-se de que o alinhamento "
            "com a liderança foi concluído."
        ),
    },
    "apoio operacao": {
        "label": "Apoio Operação",
        "limit_seconds": 30 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: Registrada ultrapassagem "
            "do limite de 30min na atividade de Apoio Operação pelo(a) "
            "colaborador(a) {name} da {unit}. Por favor, orientar o retorno "
            "ao atendimento caso não seja mais necessário continuar com o "
            "apoio à operação."
        ),
    },
    "pausa encerramento": {
        "label": "Pausa Encerramento",
        "limit_seconds": 20 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: O(A) colaborador(a) "
            "{name} ({unit}) excedeu o limite de 20min para a Pausa "
            "Encerramento. Por favor, verificar se há dificuldades na "
            "finalização dos últimos chamados."
        ),
    },
    "pre pausa": {
        "label": "Pré-pausa",
        "limit_seconds": 30 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: Identificada ultrapassagem "
            "no tempo de Pré-pausa (limite de 30min) do(a) colaborador(a) "
            "{name} ({unit}). Por favor, checar a transição para a pausa "
            "programada ou fila de atendimento."
        ),
    },
    "problemas tecnicos sistemicos": {
        "label": "Problemas Técnicos / Sistêmicos",
        "limit_seconds": 30 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: O(A) colaborador(a) "
            "{name} ({unit}) ultrapassou os 30min em pausa de Problemas "
            "Técnicos/Sistêmicos. Por favor, intervir para validar se há "
            "necessidade de abertura de chamado junto ao suporte de TI."
        ),
    },
    "treinamento capacitacao": {
        "label": "Treinamento / Capacitação",
        "limit_seconds": 60 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: Registrado estouro no "
            "tempo limite de 1h para a pausa Treinamento do(a) colaborador(a) "
            "{name} ({unit}). Por favor, orientar o encerramento da "
            "capacitação."
        ),
    },
    "descanso": {
        "label": "Descanso",
        "limit_seconds": 10 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: O(A) colaborador(a) "
            "{name} ({unit}) excedeu os 10min estipulados para a pausa "
            "regulamentar de Descanso. Por favor, solicitar o retorno à fila."
        ),
    },
    "pausa transferencia": {
        "label": "Pausa Transferência",
        "limit_seconds": 20 * 60,
        "alert": (
            "📢 Notificação de Estouro de Pausa: Identificado excesso de "
            "tempo na Pausa Transferência (limite de 20min) do(a) "
            "colaborador(a) {name} ({unit}). Por favor, averiguar se há "
            "inconsistências na mudança de filas ou distribuidoras."
        ),
    },
    "pausa sem justificativa": {
        "label": "Pausa Sem Justificativa",
        "limit_seconds": 10 * 60,
        "alert": (
            "📢 Notificação de Pausa: Identificado que o(a) colaborador(a) "
            "{name} ({unit}) encontra-se em status de pausa sem justificativa "
            "selecionada no sistema. Por favor, alertar o colaborador para "
            "regularizar o status."
        ),
    },
}


class NamedBytesIO(BytesIO):
    """Arquivo XLSX em memória com nome compatível com o parser."""

    def __init__(
        self,
        content: bytes,
        name: str,
        unit_code_hint: str | None = None,
    ) -> None:
        super().__init__(content)
        self.name = name
        self.unit_code_hint = unit_code_hint



def inject_styles() -> None:
    """Aplica o tema visual sem alterar componentes de dados."""

    st.markdown(
        """
        <style>
        :root {
            --purple-950: #24103d;
            --purple-900: #331553;
            --purple-800: #4a1f73;
            --purple-700: #643296;
            --purple-600: #7c46ad;
            --purple-100: #eee6f7;
            --purple-50: #f7f3fb;
            --ink-900: #221c2a;
            --ink-600: #6f6877;
            --line: #e7e1eb;
            --success: #178a55;
            --success-bg: #eaf8f1;
            --danger: #c23b48;
            --danger-bg: #fff0f1;
            --warning: #a36b00;
            --warning-bg: #fff8df;
        }

        .stApp {
            background:
                radial-gradient(circle at 95% 0%, rgba(124, 70, 173, .10), transparent 28rem),
                #f7f5f9;
            color: var(--ink-900);
        }

        [data-testid="stHeader"] {
            background: rgba(247, 245, 249, .86);
        }

        [data-testid="stMainBlockContainer"] {
            max-width: 1500px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, var(--purple-950), var(--purple-900));
            border-right: 0;
        }

        [data-testid="stSidebar"] * {
            color: #ffffff;
        }

        [data-testid="stSidebar"] .stCaption,
        [data-testid="stSidebar"] small {
            color: rgba(255, 255, 255, .68) !important;
        }

        [data-testid="stSidebar"] hr {
            border-color: rgba(255, 255, 255, .14);
        }

        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            background: rgba(255, 255, 255, .10);
            border-color: rgba(255, 255, 255, .18);
        }

        [data-testid="stSidebar"] input::placeholder {
            color: rgba(255, 255, 255, .48);
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] > button {
            min-height: 2.8rem;
            border: 0;
            border-radius: 12px;
            background: linear-gradient(135deg, var(--purple-700), var(--purple-600));
            color: #ffffff;
            font-weight: 700;
            box-shadow: 0 9px 22px rgba(74, 31, 115, .18);
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            background: linear-gradient(135deg, var(--purple-800), var(--purple-700));
            color: #ffffff;
            border: 0;
        }

        [data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button {
            width: 100%;
            background: #ffffff;
            color: var(--purple-900);
            box-shadow: none;
        }

        [data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button:hover {
            background: var(--purple-100);
            color: var(--purple-950);
        }

        .hero {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.5rem;
            margin-bottom: 1.35rem;
            padding: 1.55rem 1.7rem;
            border: 1px solid rgba(100, 50, 150, .12);
            border-radius: 22px;
            background: linear-gradient(135deg, #ffffff 15%, var(--purple-50));
            box-shadow: 0 14px 38px rgba(45, 25, 62, .07);
        }

        .hero-kicker {
            margin-bottom: .38rem;
            color: var(--purple-700);
            font-size: .75rem;
            font-weight: 800;
            letter-spacing: .11em;
            text-transform: uppercase;
        }

        .hero h1 {
            margin: 0;
            color: var(--ink-900);
            font-size: clamp(1.65rem, 3vw, 2.55rem);
            line-height: 1.1;
        }

        .hero p {
            max-width: 760px;
            margin: .65rem 0 0;
            color: var(--ink-600);
            font-size: .98rem;
        }

        .hero-badge {
            flex: 0 0 auto;
            padding: .72rem 1rem;
            border: 1px solid #ddd0eb;
            border-radius: 999px;
            background: #ffffff;
            color: var(--purple-800);
            font-size: .83rem;
            font-weight: 800;
            white-space: nowrap;
        }

        .section-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.75rem 0 .85rem;
        }

        .section-title h2 {
            margin: 0;
            color: var(--ink-900);
            font-size: 1.35rem;
        }

        .section-title p {
            margin: .25rem 0 0;
            color: var(--ink-600);
            font-size: .87rem;
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            padding: .45rem .72rem;
            border-radius: 999px;
            font-size: .75rem;
            font-weight: 800;
            white-space: nowrap;
        }

        .status-pill.success {
            background: var(--success-bg);
            color: var(--success);
        }

        .status-pill.error {
            background: var(--danger-bg);
            color: var(--danger);
        }

        .metric-card {
            min-height: 120px;
            padding: 1.05rem 1.1rem;
            border: 1px solid var(--line);
            border-radius: 17px;
            background: #ffffff;
            box-shadow: 0 8px 24px rgba(45, 25, 62, .055);
        }

        .metric-card.accent {
            border-color: rgba(100, 50, 150, .18);
            background: linear-gradient(145deg, #ffffff, var(--purple-50));
        }

        .metric-label {
            display: flex;
            align-items: center;
            gap: .45rem;
            margin-bottom: .72rem;
            color: var(--ink-600);
            font-size: .78rem;
            font-weight: 700;
        }

        .metric-icon {
            display: grid;
            width: 1.7rem;
            height: 1.7rem;
            place-items: center;
            border-radius: 8px;
            background: var(--purple-100);
            font-size: .85rem;
        }

        .metric-value {
            color: var(--purple-900);
            font-size: clamp(1.45rem, 2.5vw, 2rem);
            font-weight: 850;
            letter-spacing: -.035em;
            line-height: 1;
        }

        .metric-note {
            min-height: 1rem;
            margin-top: .62rem;
            color: #8a8391;
            font-size: .71rem;
        }

        .empty-state {
            padding: 3rem 2rem;
            border: 1px dashed #cfc2dc;
            border-radius: 22px;
            background: rgba(255, 255, 255, .68);
            text-align: center;
        }

        .empty-state .empty-icon {
            font-size: 2.45rem;
        }

        .empty-state h3 {
            margin: .85rem 0 .35rem;
            color: var(--purple-900);
        }

        .empty-state p {
            max-width: 610px;
            margin: 0 auto;
            color: var(--ink-600);
        }

        .queue-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: .55rem;
            margin: .3rem 0 1rem;
        }

        .queue-chip {
            padding: .47rem .72rem;
            border: 1px solid #ddd1e9;
            border-radius: 999px;
            background: var(--purple-50);
            color: var(--purple-800);
            font-size: .78rem;
            font-weight: 750;
        }

        [data-baseweb="tab-list"] {
            gap: .45rem;
            margin-top: .25rem;
        }

        [data-baseweb="tab"] {
            height: 2.8rem;
            padding: 0 1rem;
            border-radius: 11px;
            background: #ffffff;
            font-weight: 700;
        }

        [aria-selected="true"][data-baseweb="tab"] {
            background: var(--purple-100);
            color: var(--purple-900);
        }

        [data-testid="stDataFrame"] {
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 15px;
            background: #ffffff;
        }

        [data-testid="stExpander"] {
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 13px;
            background: rgba(255, 255, 255, .78);
        }

        @media (max-width: 780px) {
            [data-testid="stMainBlockContainer"] {
                padding-left: 1rem;
                padding-right: 1rem;
            }

            .hero {
                align-items: flex-start;
                flex-direction: column;
            }

            .section-title {
                align-items: flex-start;
                flex-direction: column;
            }
        }

        /* Campos de usuário e senha: fundo claro e texto legível. */
        [data-testid="stSidebar"] input {
            background-color: #ffffff !important;
            color: #2d163d !important;
            -webkit-text-fill-color: #2d163d !important;
            caret-color: #643296 !important;
        }

        /* Placeholder dos campos de usuário e senha. */
        [data-testid="stSidebar"] input::placeholder {
            color: #8b8093 !important;
            -webkit-text-fill-color: #8b8093 !important;
            opacity: 1 !important;
        }

        /* Contêiner externo dos campos de texto. */
        [data-testid="stSidebar"] [data-baseweb="input"] > div {
            background-color: #ffffff !important;
            border-color: rgba(255, 255, 255, .25) !important;
        }

        /* Visual inspirado no dashboard publicado no GPT Site. */
        :root {
            --site-navy: #172033;
            --site-sidebar: #1f2937;
            --site-purple: #7c3aed;
            --site-purple-dark: #6d28d9;
            --site-purple-soft: #f3e8ff;
            --site-green: #0d9488;
            --site-green-soft: #e8faf7;
            --site-ink: #172033;
            --site-muted: #64748b;
            --site-line: #e4e9f0;
            --site-canvas: #f4f6f8;
        }

        html, body, [class*="css"] {
            font-family: Inter, ui-sans-serif, system-ui, -apple-system,
                BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .stApp {
            color: var(--site-ink);
            background: var(--site-canvas);
        }

        [data-testid="stHeader"] {
            height: 2.2rem;
            background: rgba(244, 246, 248, .92);
            backdrop-filter: blur(10px);
        }

        [data-testid="stMainBlockContainer"] {
            width: 100%;
            max-width: 1680px;
            padding: 1.15rem 1.65rem 3rem;
        }

        [data-testid="stSidebar"] {
            width: 230px !important;
            background: linear-gradient(
                180deg,
                var(--site-sidebar) 0%,
                var(--site-navy) 58%,
                #111827 100%
            );
            border-right: 0;
        }

        [data-testid="stSidebarContent"] {
            padding: .8rem .65rem 1rem;
        }

        [data-testid="stSidebar"] [data-testid="stForm"] {
            padding: 0 .15rem;
            border: 0;
            background: transparent;
        }

        [data-testid="stSidebar"] h3 {
            margin-top: .7rem;
            color: #f8fafc;
            font-size: .78rem;
            font-weight: 750;
        }

        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
            color: #cbd5e1 !important;
            font-size: .69rem !important;
            font-weight: 650 !important;
        }

        [data-testid="stSidebar"] hr {
            margin: .85rem 0;
            border-color: rgba(255, 255, 255, .08);
        }

        .side-brand {
            display: flex;
            align-items: center;
            gap: .65rem;
            min-height: 48px;
            padding: .15rem .4rem .9rem;
            margin-bottom: .75rem;
            color: #ffffff;
            border-bottom: 1px solid rgba(255, 255, 255, .08);
        }

        .side-brand span {
            display: grid;
            width: 30px;
            height: 30px;
            place-items: center;
            border-radius: 8px;
            color: #ffffff;
            background: linear-gradient(135deg, #0f766e, #14b8a6);
            font-size: .58rem;
            font-weight: 900;
            box-shadow: 0 0 0 3px rgba(20, 184, 166, .16);
        }

        .side-brand strong {
            color: #ffffff;
            font-size: .82rem;
            letter-spacing: -.01em;
        }

        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            min-height: 38px;
            color: #334155 !important;
            -webkit-text-fill-color: #334155 !important;
            background: #ffffff !important;
            border: 1px solid #dce3eb !important;
            border-radius: 7px !important;
        }

        [data-testid="stSidebar"] input:focus {
            border-color: #5ccdc1 !important;
            box-shadow: 0 0 0 3px rgba(13, 148, 136, .12) !important;
        }

        [data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button {
            min-height: 41px;
            margin-top: .45rem;
            border: 1px solid var(--site-purple);
            border-radius: 7px;
            color: #ffffff;
            background: linear-gradient(
                135deg,
                var(--site-purple),
                var(--site-purple-dark)
            );
            box-shadow: 0 4px 12px rgba(124, 58, 237, .2);
        }

        [data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button:hover {
            color: #ffffff;
            background: var(--site-purple-dark);
        }

        .hero {
            min-height: 76px;
            margin: 0 0 1rem;
            padding: .8rem 1.25rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: rgba(255, 255, 255, .97);
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        .hero-kicker {
            margin: 0 0 .22rem;
            color: var(--site-green);
            font-size: .57rem;
            font-weight: 850;
            letter-spacing: .12em;
        }

        .hero h1 {
            color: var(--site-ink);
            font-size: 1.15rem;
            font-weight: 780;
            letter-spacing: -.025em;
        }

        .hero p {
            display: none;
        }

        .hero-badge {
            padding: .44rem .65rem;
            border: 1px solid #dfe5ec;
            border-radius: 6px;
            color: var(--site-muted);
            background: #f1f4f7;
            font-size: .65rem;
            font-weight: 700;
        }

        .section-title {
            align-items: flex-end;
            margin: 1.2rem 0 .75rem;
        }

        .section-title h2 {
            color: var(--site-ink);
            font-size: 1.18rem;
            font-weight: 780;
            letter-spacing: -.025em;
        }

        .section-title p {
            margin-top: .2rem;
            color: var(--site-muted);
            font-size: .68rem;
        }

        .status-pill {
            padding: .38rem .58rem;
            border-radius: 999px;
            font-size: .58rem;
            letter-spacing: .01em;
        }

        .status-pill.success {
            color: #0f766e;
            background: var(--site-green-soft);
            border: 1px solid #bde9e2;
        }

        .status-pill.error {
            color: #b42332;
            background: #fff0f0;
            border: 1px solid #f6caca;
        }

        .metric-card,
        .metric-card.accent {
            min-height: 116px;
            padding: 1rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        .metric-card.accent {
            border-color: #ddd1f4;
        }

        .metric-label {
            gap: .62rem;
            margin-bottom: .68rem;
            color: var(--site-muted);
            font-size: .64rem;
        }

        .metric-icon {
            width: 35px;
            height: 35px;
            border-radius: 50%;
            color: var(--site-green);
            background: var(--site-green-soft);
            font-size: .72rem;
            font-weight: 900;
        }

        .metric-card.accent .metric-icon {
            color: var(--site-purple);
            background: var(--site-purple-soft);
        }

        .metric-value {
            color: var(--site-ink);
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: -.035em;
        }

        .metric-note {
            margin-top: .4rem;
            color: #8a97a9;
            font-size: .61rem;
        }

        .overall-goal-card {
            margin: .75rem 0 .9rem;
            padding: 1.05rem 1.15rem;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, .24);
            border-radius: 11px;
            color: #ffffff;
            background:
                radial-gradient(
                    circle at 92% 15%,
                    rgba(216, 180, 254, .32),
                    transparent 28%
                ),
                linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%);
            box-shadow: 0 8px 22px rgba(91, 33, 182, .22);
        }

        .overall-goal-top,
        .overall-goal-detail {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .overall-goal-label {
            display: block;
            color: rgba(255, 255, 255, .82);
            font-size: .65rem;
            font-weight: 750;
            letter-spacing: .035em;
            text-transform: uppercase;
        }

        .overall-goal-value {
            display: block;
            margin-top: .22rem;
            color: #ffffff;
            font-size: clamp(1.7rem, 3vw, 2.25rem);
            font-weight: 850;
            letter-spacing: -.04em;
            line-height: 1;
        }

        .overall-goal-badge {
            flex: 0 0 auto;
            padding: .36rem .58rem;
            border: 1px solid rgba(255, 255, 255, .25);
            border-radius: 999px;
            color: #ffffff;
            background: rgba(255, 255, 255, .13);
            font-size: .61rem;
            font-weight: 750;
        }

        .overall-goal-track {
            height: .58rem;
            margin-top: .8rem;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(255, 255, 255, .2);
        }

        .overall-goal-fill {
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, #ffffff, #d8b4fe);
            box-shadow: 0 0 10px rgba(255, 255, 255, .28);
        }

        .overall-goal-detail {
            margin-top: .55rem;
            color: rgba(255, 255, 255, .86);
            font-size: .64rem;
        }

        .overall-goal-detail strong {
            color: #ffffff;
            font-weight: 800;
        }

        [data-baseweb="tab-list"] {
            gap: .25rem;
            padding: .35rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .025);
        }

        [data-baseweb="tab"] {
            height: 2.35rem;
            padding: 0 .8rem;
            border-radius: 7px;
            color: #64748b;
            background: transparent;
            font-size: .68rem;
            font-weight: 700;
        }

        [aria-selected="true"][data-baseweb="tab"] {
            color: #5b21b6;
            background: var(--site-purple-soft);
            box-shadow: inset 3px 0 0 var(--site-purple);
        }

        [data-testid="stDataFrame"],
        [data-testid="stExpander"] {
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .025);
        }

        [data-testid="stExpander"] summary {
            font-size: .7rem;
            font-weight: 720;
        }

        [data-testid="stAlert"] {
            border-radius: 7px;
            font-size: .72rem;
        }

        [data-testid="stProgress"] > div > div > div > div {
            background: linear-gradient(
                90deg,
                var(--site-purple),
                var(--site-green)
            );
        }

        .queue-chip-row {
            gap: .4rem;
            margin-bottom: .75rem;
        }

        .queue-chip {
            padding: .35rem .55rem;
            border-color: #dfd1f4;
            color: #5b21b6;
            background: var(--site-purple-soft);
            font-size: .61rem;
        }

        .empty-state {
            padding: 2.4rem 1.5rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        .empty-state h3 {
            color: var(--site-ink);
            font-size: 1rem;
        }

        .empty-state p {
            color: var(--site-muted);
            font-size: .74rem;
        }

        .stDownloadButton > button,
        .stButton > button {
            min-height: 2.35rem;
            padding: .45rem .8rem;
            border: 1px solid var(--site-purple);
            border-radius: 7px;
            color: #ffffff;
            background: linear-gradient(
                135deg,
                var(--site-purple),
                var(--site-purple-dark)
            );
            font-size: .68rem;
            font-weight: 750;
            box-shadow: 0 4px 12px rgba(124, 58, 237, .18);
        }

        .unit-overview-heading {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.4rem 0 .65rem;
        }

        .unit-overview-heading h2 {
            margin: 0;
            color: var(--site-navy);
            font-size: 1.02rem;
            letter-spacing: -.02em;
        }

        .unit-overview-heading p {
            margin: .18rem 0 0;
            color: var(--site-muted);
            font-size: .72rem;
        }

        .unit-card-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .75rem;
            margin-bottom: .7rem;
        }

        .unit-card {
            min-width: 0;
            padding: .95rem;
            background: #fff;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        .unit-card.alert {
            border-color: #fecaca;
        }

        .unit-card-head,
        .unit-card-status,
        .unit-card-total,
        .unit-card-stat,
        .unit-card-queue {
            display: flex;
            align-items: center;
        }

        .unit-card-head {
            justify-content: space-between;
            gap: .7rem;
            margin-bottom: .85rem;
        }

        .unit-card-identity {
            display: flex;
            align-items: center;
            min-width: 0;
            gap: .55rem;
        }

        .unit-card-symbol {
            display: grid;
            place-items: center;
            width: 1.9rem;
            height: 1.9rem;
            flex: 0 0 auto;
            color: var(--site-purple);
            background: var(--site-purple-soft);
            border-radius: 7px;
            font-size: .88rem;
            font-weight: 800;
        }

        .unit-card-title {
            min-width: 0;
        }

        .unit-card-title strong {
            display: block;
            overflow: hidden;
            color: var(--site-navy);
            font-size: .78rem;
            line-height: 1.2;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .unit-card-title small {
            display: block;
            margin-top: .15rem;
            overflow: hidden;
            color: var(--site-muted);
            font-size: .58rem;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .unit-card-status {
            flex: 0 0 auto;
            gap: .28rem;
            color: #047857;
            font-size: .55rem;
            font-weight: 750;
        }

        .unit-card-status::before {
            content: "";
            width: .38rem;
            height: .38rem;
            background: #14b8a6;
            border-radius: 50%;
            box-shadow: 0 0 0 3px rgba(20, 184, 166, .1);
        }

        .unit-card-status.alert {
            color: #b91c1c;
        }

        .unit-card-status.alert::before {
            background: #ef4444;
            box-shadow: 0 0 0 3px rgba(239, 68, 68, .1);
        }

        .unit-card-total {
            align-items: flex-end;
            justify-content: space-between;
            gap: .75rem;
            padding-bottom: .75rem;
            border-bottom: 1px solid #edf0f4;
        }

        .unit-card-total span,
        .unit-card-tma span,
        .unit-card-stat span,
        .unit-card-queue span {
            color: #7a879a;
            font-size: .58rem;
        }

        .unit-card-total strong {
            display: block;
            margin-top: .15rem;
            color: var(--site-navy);
            font-size: 1.6rem;
            line-height: 1;
            letter-spacing: -.045em;
        }

        .unit-card-tma {
            text-align: right;
        }

        .unit-card-tma strong {
            display: block;
            margin-top: .18rem;
            color: var(--site-green);
            font-size: .88rem;
        }

        .unit-card-stats {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: .45rem .8rem;
            padding: .7rem 0;
        }

        .unit-card-stat,
        .unit-card-queue {
            justify-content: space-between;
            min-width: 0;
            gap: .5rem;
        }

        .unit-card-stat strong,
        .unit-card-queue strong {
            color: var(--site-navy);
            font-size: .72rem;
        }

        .unit-card-stat.logged {
            margin: -.2rem;
            padding: .2rem;
            background: var(--site-green-soft);
            border-radius: 5px;
        }

        .unit-card-stat.logged span,
        .unit-card-stat.logged strong {
            color: #0f766e;
            font-weight: 800;
        }

        .unit-card-stat.carryover {
            grid-column: 1 / -1;
            margin: -.05rem -.2rem;
            padding: .35rem .4rem;
            border-radius: 5px;
            background: #fff7ed;
        }

        .unit-card-stat.carryover span,
        .unit-card-stat.carryover strong {
            color: #c2410c;
            font-weight: 800;
        }

        .unit-card-queues {
            display: grid;
            gap: .42rem;
            padding-top: .65rem;
            border-top: 1px solid #edf0f4;
            border-bottom: 1px solid #edf0f4;
            padding-bottom: .65rem;
        }

        .unit-card-queue span {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .productivity-insights-heading {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.4rem 0 .65rem;
        }

        .productivity-insights-heading h2 {
            margin: 0;
            color: var(--site-navy);
            font-size: 1.02rem;
            letter-spacing: -.02em;
        }

        .productivity-insights-heading p {
            margin: .18rem 0 0;
            color: var(--site-muted);
            font-size: .72rem;
        }

        [data-testid="stVegaLiteChart"] {
            width: 100%;
            max-width: 100%;
            padding: .75rem .85rem .45rem;
            overflow: hidden;
            box-sizing: border-box;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        [data-testid="stVegaLiteChart"] > div {
            width: 100% !important;
            max-width: 100% !important;
            overflow: hidden;
        }

        .productivity-goal-heading {
            margin: 1.05rem 0 .6rem;
        }

        .productivity-goal-heading h3 {
            margin: 0;
            color: var(--site-navy);
            font-size: .9rem;
            letter-spacing: -.015em;
        }

        .productivity-goal-heading p {
            margin: .18rem 0 0;
            color: var(--site-muted);
            font-size: .66rem;
        }

        .productivity-goal-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .7rem;
            margin-bottom: .8rem;
        }

        .productivity-goal-card {
            min-width: 0;
            padding: .8rem .85rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        .productivity-goal-top,
        .productivity-goal-detail {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .65rem;
        }

        .productivity-goal-name {
            overflow: hidden;
            color: var(--site-navy);
            font-size: .72rem;
            font-weight: 750;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .productivity-goal-percent {
            flex: 0 0 auto;
            color: var(--site-purple-dark);
            font-size: .9rem;
            font-weight: 820;
        }

        .productivity-goal-track {
            height: .48rem;
            margin-top: .58rem;
            overflow: hidden;
            border-radius: 999px;
            background: #e8edf3;
        }

        .productivity-goal-fill {
            height: 100%;
            border-radius: inherit;
            background: #ef4444;
        }

        .productivity-goal-fill.warning {
            background: #f59e0b;
        }

        .productivity-goal-fill.complete {
            background: var(--site-green);
        }

        .productivity-goal-detail {
            margin-top: .46rem;
            color: var(--site-muted);
            font-size: .58rem;
        }

        .productivity-goal-note {
            margin: -.1rem 0 .75rem;
            color: var(--site-muted);
            font-size: .6rem;
        }

        .tme-page-heading {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.15rem 0 .8rem;
        }

        .tme-page-kicker {
            display: block;
            margin-bottom: .3rem;
            color: var(--site-green);
            font-size: .6rem;
            font-weight: 850;
            letter-spacing: .12em;
            text-transform: uppercase;
        }

        .tme-page-heading h2 {
            margin: 0;
            color: var(--site-navy);
            font-size: 1.18rem;
            letter-spacing: -.025em;
        }

        .tme-page-heading p {
            margin: .2rem 0 0;
            color: var(--site-muted);
            font-size: .7rem;
        }

        .tme-legend {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: .65rem 1.25rem;
            margin-bottom: .8rem;
            padding: .75rem .9rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .025);
        }

        .tme-legend-item {
            display: inline-flex;
            align-items: center;
            gap: .38rem;
            color: #475569;
            font-size: .65rem;
            font-weight: 700;
        }

        .tme-legend-note {
            margin-left: auto;
            color: var(--site-muted);
            font-size: .62rem;
        }

        .tme-dot {
            display: inline-block;
            width: .58rem;
            height: .58rem;
            flex: 0 0 auto;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: inset 0 -1px 2px rgba(15, 23, 42, .18);
        }

        .tme-dot.equal {
            background: #f97316;
        }

        .tme-dot.above {
            background: #dc2648;
        }

        .tme-card-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: .7rem;
            margin: .85rem 0 1rem;
        }

        .tme-unit-card {
            min-width: 0;
            padding: .85rem;
            border: 1px solid var(--site-line);
            border-radius: 9px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .035);
        }

        .tme-unit-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .5rem;
            margin-bottom: .7rem;
            padding-bottom: .55rem;
            border-bottom: 1px solid #edf0f4;
        }

        .tme-unit-head strong {
            overflow: hidden;
            color: var(--site-navy);
            font-size: .78rem;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .tme-unit-head small {
            flex: 0 0 auto;
            color: var(--site-muted);
            font-size: .55rem;
        }

        .tme-indicator {
            padding: .7rem;
            border: 1px solid #bde9e2;
            border-radius: 8px;
            background: var(--site-green-soft);
        }

        .tme-indicator + .tme-indicator {
            margin-top: .55rem;
        }

        .tme-indicator.equal {
            border-color: #fed7aa;
            background: #fff7ed;
        }

        .tme-indicator.above {
            border-color: #fecdd3;
            background: #fff1f2;
        }

        .tme-indicator-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .4rem;
        }

        .tme-indicator-name {
            display: inline-flex;
            align-items: center;
            min-width: 0;
            gap: .35rem;
            color: var(--site-navy);
            font-size: .62rem;
            font-weight: 780;
        }

        .tme-indicator-limit {
            flex: 0 0 auto;
            color: var(--site-muted);
            font-size: .53rem;
        }

        .tme-indicator-value {
            display: block;
            margin-top: .62rem;
            color: var(--site-navy);
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                "Liberation Mono", monospace;
            font-size: 1.05rem;
            font-weight: 800;
            letter-spacing: .04em;
            text-align: center;
        }

        .tme-indicator-tickets {
            display: block;
            margin-top: .22rem;
            color: var(--site-muted);
            font-size: .53rem;
            text-align: center;
        }

        .tme-report-heading {
            margin: 1.2rem 0 .55rem;
        }

        .tme-report-heading h3 {
            margin: 0;
            color: var(--site-navy);
            font-size: .92rem;
        }

        .tme-report-heading p {
            margin: .2rem 0 0;
            color: var(--site-muted);
            font-size: .65rem;
        }

        @media (max-width: 1350px) {
            .tme-card-grid {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
        }

        @media (max-width: 1100px) {
            .unit-card-grid,
            .productivity-goal-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 780px) {
            [data-testid="stSidebar"] {
                width: 100% !important;
            }

            [data-testid="stMainBlockContainer"] {
                padding: .8rem .75rem 2rem;
            }

            .hero {
                min-height: auto;
                padding: .8rem 1rem;
            }

            .hero-badge {
                align-self: flex-start;
            }

            [data-baseweb="tab-list"] {
                overflow-x: auto;
            }

            .unit-card-grid,
            .productivity-goal-grid {
                grid-template-columns: 1fr;
            }

            .productivity-insights-heading {
                align-items: flex-start;
                flex-direction: column;
            }

            .tme-page-heading {
                align-items: flex-start;
                flex-direction: column;
            }

            .tme-legend-note {
                width: 100%;
                margin-left: 0;
            }

            .tme-card-grid {
                grid-template-columns: 1fr;
            }

            .overall-goal-top,
            .overall-goal-detail {
                align-items: flex-start;
                flex-direction: column;
                gap: .42rem;
            }

            .overall-goal-badge {
                align-self: flex-start;
            }
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(reference_date: date | None = None) -> None:
    """Renderiza o cabeçalho principal."""

    badge = (
        reference_date.strftime("%d/%m/%Y")
        if reference_date
        else "Monitoramento operacional"
    )
    st.markdown(
        f"""
        <section class="hero">
            <div>
                <div class="hero-kicker">Central operacional</div>
                <h1>Painel de Monitoramento Operacional</h1>
                <p>
                    Produtividade, volumetria e tempo médio humano das
                    distribuidoras em uma visão única.
                </p>
            </div>
            <div class="hero-badge">📅 {html.escape(badge)}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(
    label: str,
    value: Any,
    icon: str,
    note: str = "",
    *,
    accent: bool = False,
) -> None:
    """Exibe um indicador sem depender do componente st.metric."""

    css_class = "metric-card accent" if accent else "metric-card"
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))
    safe_note = html.escape(str(note))
    st.markdown(
        f"""
        <div class="{css_class}">
            <div class="metric-label">
                <span class="metric-icon">{html.escape(icon)}</span>
                <span>{safe_label}</span>
            </div>
            <div class="metric-value">{safe_value}</div>
            <div class="metric-note">{safe_note or '&nbsp;'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overall_goal_card(actual: int, goal: int) -> dict[str, Any]:
    """Exibe o cumprimento da meta geral diária fixa das cinco unidades."""

    percentage = (actual / goal * 100) if goal else 0.0
    displayed_percentage = f"{percentage:.1f}".replace(".", ",")
    fill_width = min(100.0, max(0.0, percentage))
    difference = actual - goal
    if difference > 0:
        progress_note = (
            f"Meta superada em {format_integer_pt(difference)} atendimentos"
        )
    elif difference == 0:
        progress_note = "Meta diária atingida"
    else:
        progress_note = (
            f"Faltam {format_integer_pt(abs(difference))} atendimentos"
        )

    st.markdown(
        dedent(
            f"""
            <section class="overall-goal-card">
                <div class="overall-goal-top">
                    <div>
                        <span class="overall-goal-label">Meta geral diária</span>
                        <strong class="overall-goal-value">{displayed_percentage}%</strong>
                    </div>
                    <span class="overall-goal-badge">Meta fixa · {format_integer_pt(goal)}</span>
                </div>
                <div
                    class="overall-goal-track"
                    role="progressbar"
                    aria-label="Cumprimento da meta geral diária"
                    aria-valuenow="{min(100, round(percentage))}"
                    aria-valuemin="0"
                    aria-valuemax="100"
                >
                    <div
                        class="overall-goal-fill"
                        style="width: {fill_width:.2f}%"
                    ></div>
                </div>
                <div class="overall-goal-detail">
                    <span>
                        <strong>{format_integer_pt(actual)}</strong> válidos hoje
                        de <strong>{format_integer_pt(goal)}</strong>
                    </span>
                    <span>{progress_note}</span>
                </div>
            </section>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    return {
        "goal": goal,
        "actual": actual,
        "percentage": round(percentage, 2),
        "remaining": max(0, goal - actual),
    }


def render_section_title(
    title: str,
    subtitle: str,
    *,
    healthy: bool = True,
) -> None:
    """Exibe título da distribuidora e seu estado de consulta."""

    status_class = "success" if healthy else "error"
    status_text = "Dados atualizados" if healthy else "Consulta com alerta"
    status_icon = "●"
    st.markdown(
        f"""
        <div class="section-title">
            <div>
                <h2>{html.escape(title)}</h2>
                <p>{html.escape(subtitle)}</p>
            </div>
            <span class="status-pill {status_class}">
                {status_icon} {status_text}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def normalize_identifier(value: Any) -> str:
    """Normaliza nomes, logins e textos do relatório para comparação."""

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    normalized = unicodedata.normalize("NFD", str(value))
    without_accents = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


def report_cell_text(value: Any) -> str:
    """Converte uma célula opcional do Excel em texto sem produzir 'nan'."""

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def is_logos_employee(login: Any, attendant: Any) -> bool:
    """Confere o login/nome usando a relação anonimizada enviada pela Logos."""

    candidates: set[str] = set()
    for raw_value in (login, attendant):
        normalized = normalize_identifier(raw_value)
        if not normalized:
            continue
        candidates.add(normalized)
        alias = LOGOS_IDENTIFIER_ALIASES.get(normalized)
        if alias:
            candidates.add(alias)

    return any(
        hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        in LOGOS_ROSTER_HASHES
        for candidate in candidates
    )


def login_report_unit(value: Any) -> str | None:
    """Associa grupo/unidade do relatório ao código usado pelo dashboard."""

    normalized = normalize_identifier(value)
    if "brasilia" in normalized or "bsb" in normalized:
        return "BRASILIA"
    if "pernambuco" in normalized or "celpe" in normalized:
        return "PERNAMBUCO"
    if "coelba" in normalized:
        return "COELBA"
    if "elektro" in normalized:
        return "ELEKTRO"
    if "cosern" in normalized:
        return "COSERN"
    return None


def pause_roster_unit(login: Any, attendant: Any) -> str | None:
    """Localiza a distribuidora no novo quadro protegido da EPS Logos."""

    candidates: list[str] = []
    for raw_value in (login, attendant):
        normalized = normalize_identifier(raw_value)
        if not normalized:
            continue
        candidates.append(normalized)
        alias = LOGOS_IDENTIFIER_ALIASES.get(normalized)
        if alias:
            candidates.append(alias)

    for candidate in candidates:
        candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        unit_code = PAUSE_ROSTER_UNIT_BY_HASH.get(candidate_hash)
        if unit_code:
            return unit_code
    return None


def pause_rule(value: Any) -> tuple[str, dict[str, Any] | None]:
    """Associa o nome retornado pela Mutant à regra de tempo cadastrada."""

    normalized = normalize_identifier(value)
    normalized = re.sub(r"^\d+\s+", "", normalized).strip()
    if normalized in PAUSE_RULES:
        return normalized, PAUSE_RULES[normalized]

    for rule_key, rule in PAUSE_RULES.items():
        if normalized and (
            normalized in rule_key or rule_key in normalized
        ):
            return rule_key, rule
    return normalized, None


def collect_current_logos_pauses(
    runtime_units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    """Consulta pausas atuais e filtra somente o novo quadro da Logos."""

    selected_unit_codes = {item["unit"].code for item in runtime_units}
    now = datetime.now(BRASILIA_TZ)
    errors: dict[str, str] = {}
    raw_by_client: dict[int, list[dict[str, Any]]] = {}
    error_by_client: dict[int, str] = {}

    for item in runtime_units:
        client = item.get("client")
        unit = item["unit"]
        if client is None:
            errors[unit.code] = (
                item.get("errors", {}).get("authentication")
                or "Autenticação indisponível."
            )
            continue

        client_identity = id(client)
        if client_identity in raw_by_client:
            if client_identity in error_by_client:
                errors[unit.code] = error_by_client[client_identity]
            continue

        try:
            raw_by_client[client_identity] = client.supervisor_agents()
        except MutantApiError as exc:
            raw_by_client[client_identity] = []
            error_by_client[client_identity] = str(exc)
            errors[unit.code] = error_by_client[client_identity]

    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    api_agents = 0
    roster_agents: set[tuple[str, str]] = set()
    paused_outside_roster = 0
    unknown_pause_types: set[str] = set()

    for records in raw_by_client.values():
        api_agents += len(records)
        for record in records:
            user = record.get("user")
            if not isinstance(user, dict):
                user = {}

            login = str(user.get("username") or "").strip()
            attendant = str(
                user.get("full_name")
                or " ".join(
                    filter(
                        None,
                        [
                            str(user.get("first_name") or "").strip(),
                            str(user.get("last_name") or "").strip(),
                        ],
                    )
                )
                or login
                or "—"
            ).strip()

            unit_code = pause_roster_unit(login, attendant)
            pause_data = record.get("work_pause_time")

            if unit_code:
                roster_agents.add((unit_code, login or normalize_identifier(attendant)))
            elif isinstance(pause_data, dict):
                paused_outside_roster += 1
                continue

            if unit_code not in selected_unit_codes:
                continue
            if not isinstance(pause_data, dict):
                continue

            raw_pause_name = str(
                pause_data.get("work_pause_time__name")
                or pause_data.get("name")
                or "Pausa não informada"
            ).strip()
            start_date = parse_api_datetime(pause_data.get("start_date"))
            if start_date is None:
                continue

            elapsed_seconds = max(
                0,
                int((now - start_date.astimezone(BRASILIA_TZ)).total_seconds()),
            )
            _, rule = pause_rule(raw_pause_name)

            if rule:
                pause_name = str(rule["label"])
                limit_seconds: int | None = int(rule["limit_seconds"])
                exceeded_seconds = max(0, elapsed_seconds - limit_seconds)
                exceeded = elapsed_seconds > limit_seconds
                status = "🔴 Extrapolada" if exceeded else "🟢 Dentro do limite"
                alert = (
                    str(rule["alert"]).format(
                        name=attendant,
                        unit=UNIT_SHORT_NAMES.get(unit_code, unit_code),
                    )
                    if exceeded
                    else ""
                )
            else:
                pause_name = raw_pause_name
                limit_seconds = None
                exceeded_seconds = 0
                exceeded = False
                status = "⚪ Limite não cadastrado"
                alert = ""
                unknown_pause_types.add(raw_pause_name)

            dedup_key = (unit_code, login or normalize_identifier(attendant))
            rows_by_key[dedup_key] = {
                "agent_id": str(record.get("id") or ""),
                "Login": login or "—",
                "Colaborador": attendant,
                "unit_code": unit_code,
                "Distribuidora": UNIT_SHORT_NAMES.get(unit_code, unit_code),
                "Tipo de pausa": pause_name,
                "Tempo atual": format_seconds(elapsed_seconds),
                "time_seconds": elapsed_seconds,
                "Limite": (
                    format_seconds(limit_seconds)
                    if limit_seconds is not None
                    else "—"
                ),
                "limit_seconds": limit_seconds,
                "Situação": status,
                "Excedido": (
                    format_seconds(exceeded_seconds) if exceeded else "—"
                ),
                "exceeded": exceeded,
                "exceeded_seconds": exceeded_seconds,
                "alert": alert,
            }

    audit = {
        "api_agents": api_agents,
        "logos_roster_agents": len(roster_agents),
        "paused_outside_roster": paused_outside_roster,
        "unknown_pause_types": sorted(unknown_pause_types),
        "updated_at": now.isoformat(),
    }
    return list(rows_by_key.values()), errors, audit


def render_pause_monitor(runtime_units: list[dict[str, Any]]) -> None:
    """Renderiza filtros, indicadores, tabela e alertas de pausa."""

    context = tuple(sorted(item["unit"].code for item in runtime_units))
    snapshot_key = "pause_monitor_snapshot_manual"
    snapshot = st.session_state.get(snapshot_key)
    if not isinstance(snapshot, dict) or snapshot.get("context") != context:
        snapshot = {
            "context": context,
            "loaded": False,
            "rows": [],
            "errors": {},
            "audit": {},
            "updated_at": None,
        }
        st.session_state[snapshot_key] = snapshot

    title_slot = st.empty()
    refresh_requested = st.button(
        "Atualizar pausas",
        key="refresh_pause_monitor",
        use_container_width=False,
    )

    raw_updated_at = snapshot.get("updated_at")
    previous_updated_at = parse_api_datetime(raw_updated_at)
    now = datetime.now(BRASILIA_TZ)
    seconds_since_refresh = (
        (now - previous_updated_at.astimezone(BRASILIA_TZ)).total_seconds()
        if previous_updated_at
        else None
    )
    automatic_refresh_due = (
        not bool(snapshot.get("loaded"))
        or seconds_since_refresh is None
        or seconds_since_refresh >= PAUSE_AUTO_REFRESH_SECONDS - 5
    )

    if refresh_requested or automatic_refresh_due:
        spinner_message = (
            "Atualizando pausas na Mutant..."
            if refresh_requested
            else "Consultando pausas automaticamente na Mutant..."
        )
        with st.spinner(spinner_message):
            rows, errors, audit = collect_current_logos_pauses(runtime_units)
        snapshot = {
            "context": context,
            "loaded": True,
            "rows": rows,
            "errors": errors,
            "audit": audit,
            "updated_at": datetime.now(BRASILIA_TZ).isoformat(),
        }
        st.session_state[snapshot_key] = snapshot

    loaded = bool(snapshot.get("loaded"))
    rows = list(snapshot.get("rows") or [])
    errors = dict(snapshot.get("errors") or {})
    audit = dict(snapshot.get("audit") or {})
    raw_updated_at = snapshot.get("updated_at")
    updated_at = parse_api_datetime(raw_updated_at)

    if updated_at:
        subtitle = (
            "Colaboradores da EPS Logos · última consulta em "
            f"{updated_at.astimezone(BRASILIA_TZ).strftime('%d/%m/%Y às %H:%M:%S')}"
        )
    else:
        subtitle = (
            "Colaboradores da EPS Logos · atualização automática a cada "
            "10 minutos ou imediata pelo botão"
        )

    with title_slot.container():
        render_section_title(
            "Monitoramento de pausas",
            subtitle,
            healthy=not errors,
        )

    if not loaded:
        st.info(
            "A primeira consulta será feita automaticamente. Se necessário, "
            "use **Atualizar pausas** para tentar novamente."
        )
        return

    exceeded_rows = [row for row in rows if row["exceeded"]]
    within_rows = [
        row
        for row in rows
        if not row["exceeded"] and row["limit_seconds"] is not None
    ]
    longest_seconds = max(
        (int(row["time_seconds"]) for row in rows),
        default=0,
    )

    summary_columns = st.columns(4)
    with summary_columns[0]:
        render_metric_card(
            "Em pausa agora",
            len(rows),
            "⏸",
            "Somente colaboradores do novo quadro Logos",
            accent=True,
        )
    with summary_columns[1]:
        render_metric_card(
            "Dentro do limite",
            len(within_rows),
            "●",
            "Pausas com limite conhecido",
        )
    with summary_columns[2]:
        render_metric_card(
            "Pausas extrapoladas",
            len(exceeded_rows),
            "!",
            "Tempo atual maior que o limite",
            accent=True,
        )
    with summary_columns[3]:
        render_metric_card(
            "Maior pausa atual",
            format_seconds(longest_seconds),
            "⌛",
            "Maior duração entre as pausas atuais",
        )

    if errors:
        for unit_code, message in errors.items():
            st.warning(
                f"{UNIT_SHORT_NAMES.get(unit_code, unit_code)}: {message}"
            )

    if not rows:
        all_units_failed = bool(runtime_units) and len(errors) >= len(
            runtime_units
        )
        if all_units_failed:
            st.error(
                "Não foi possível consultar as pausas na Mutant. Os valores "
                "zerados da conferência indicam ausência de resposta da API, "
                "e não ausência de colaboradores em pausa."
            )
        else:
            st.info(
                "Nenhum colaborador do novo quadro Logos está em pausa neste "
                "momento."
            )
        with st.expander("Conferência da consulta de pausas"):
            st.json(audit)
        return

    distributor_options = sorted({row["Distribuidora"] for row in rows})
    pause_type_options = sorted({row["Tipo de pausa"] for row in rows})
    distributor_widget_options = ["Todas", *distributor_options]
    if st.session_state.get("pause_distributor_filter") not in (
        None,
        *distributor_widget_options,
    ):
        st.session_state["pause_distributor_filter"] = "Todas"
    if "pause_type_filter" in st.session_state:
        st.session_state["pause_type_filter"] = [
            value
            for value in st.session_state["pause_type_filter"]
            if value in pause_type_options
        ]
    filter_columns = st.columns([1, 1.5, 1.2, 1.3])

    with filter_columns[0]:
        distributor_filter = st.selectbox(
            "Distribuidora",
            distributor_widget_options,
            key="pause_distributor_filter",
        )
    with filter_columns[1]:
        pause_type_filter = st.multiselect(
            "Tipo de pausa",
            pause_type_options,
            default=pause_type_options,
            key="pause_type_filter",
        )
    with filter_columns[2]:
        status_filter = st.selectbox(
            "Situação",
            [
                "Todas",
                "Extrapoladas",
                "Dentro do limite",
                "Limite não cadastrado",
            ],
            key="pause_status_filter",
        )
    with filter_columns[3]:
        order_filter = st.selectbox(
            "Organizar por",
            [
                "Extrapoladas primeiro",
                "Maior tempo de pausa",
                "Menor tempo de pausa",
                "Tipo de pausa",
                "Distribuidora",
            ],
            key="pause_order_filter",
        )

    filtered_rows = list(rows)
    if distributor_filter != "Todas":
        filtered_rows = [
            row
            for row in filtered_rows
            if row["Distribuidora"] == distributor_filter
        ]
    filtered_rows = [
        row
        for row in filtered_rows
        if row["Tipo de pausa"] in pause_type_filter
    ]
    if status_filter == "Extrapoladas":
        filtered_rows = [row for row in filtered_rows if row["exceeded"]]
    elif status_filter == "Dentro do limite":
        filtered_rows = [
            row
            for row in filtered_rows
            if not row["exceeded"] and row["limit_seconds"] is not None
        ]
    elif status_filter == "Limite não cadastrado":
        filtered_rows = [
            row for row in filtered_rows if row["limit_seconds"] is None
        ]

    if order_filter == "Maior tempo de pausa":
        filtered_rows.sort(key=lambda row: -int(row["time_seconds"]))
    elif order_filter == "Menor tempo de pausa":
        filtered_rows.sort(key=lambda row: int(row["time_seconds"]))
    elif order_filter == "Tipo de pausa":
        filtered_rows.sort(
            key=lambda row: (
                normalize_identifier(row["Tipo de pausa"]),
                -int(row["time_seconds"]),
            )
        )
    elif order_filter == "Distribuidora":
        filtered_rows.sort(
            key=lambda row: (
                normalize_identifier(row["Distribuidora"]),
                -int(row["time_seconds"]),
            )
        )
    else:
        filtered_rows.sort(
            key=lambda row: (
                not bool(row["exceeded"]),
                -int(row["exceeded_seconds"]),
                -int(row["time_seconds"]),
            )
        )

    table_rows = [
        {
            "Situação": row["Situação"],
            "Colaborador": row["Colaborador"],
            "Distribuidora": row["Distribuidora"],
            "Tipo de pausa": row["Tipo de pausa"],
            "Tempo atual": row["Tempo atual"],
            "Limite": row["Limite"],
            "Excedido": row["Excedido"],
        }
        for row in filtered_rows
    ]

    if table_rows:
        st.dataframe(
            pd.DataFrame(table_rows),
            use_container_width=True,
            hide_index=True,
            height=min(620, 42 + 35 * len(table_rows)),
            column_config={
                "Situação": st.column_config.TextColumn(width="medium"),
                "Colaborador": st.column_config.TextColumn(width="large"),
                "Distribuidora": st.column_config.TextColumn(width="small"),
                "Tipo de pausa": st.column_config.TextColumn(width="medium"),
                "Tempo atual": st.column_config.TextColumn(width="small"),
                "Limite": st.column_config.TextColumn(width="small"),
                "Excedido": st.column_config.TextColumn(width="small"),
            },
        )
    else:
        st.info("Nenhuma pausa corresponde aos filtros selecionados.")

    visible_alerts = [
        row for row in filtered_rows if row["exceeded"] and row["alert"]
    ]
    if visible_alerts:
        with st.expander(
            f"Alertas prontos para copiar ({len(visible_alerts)})",
            expanded=False,
        ):
            for position, row in enumerate(visible_alerts):
                st.markdown(
                    f"**{row['Colaborador']} · {row['Distribuidora']} · "
                    f"{row['Tipo de pausa']}**"
                )
                st.code(row["alert"], language=None)
                if position < len(visible_alerts) - 1:
                    st.divider()

    with st.expander("Conferência da consulta de pausas", expanded=False):
        st.write(
            f"**Atendentes recebidos da API:** {audit['api_agents']}  "
            f"\n**Colaboradores reconhecidos no quadro Logos:** "
            f"{audit['logos_roster_agents']}  "
            f"\n**Pausados de outras empresas desconsiderados:** "
            f"{audit['paused_outside_roster']}"
        )
        if audit["unknown_pause_types"]:
            st.warning(
                "Tipos sem limite cadastrado: "
                + ", ".join(audit["unknown_pause_types"])
            )


def empty_headcount_result() -> dict[str, Any]:
    """Estrutura padrão quando nenhum relatório Login/Logout foi importado."""

    return {
        "counts": {unit.code: None for unit in UNITS},
        "daily_counts": {unit.code: None for unit in UNITS},
        "people": [],
        "files": [],
        "total_online_logins": 0,
        "logos_online": 0,
        "other_companies_online": 0,
        "duplicates": 0,
        "warnings": [],
        "loaded_units": [],
        "source_by_unit": {},
    }


def parse_login_logout_reports(
    files: list[Any],
    *,
    origin: str = "Upload manual",
) -> dict[str, Any]:
    """Consolida relatórios Login/Logout e conta somente colaboradores Logos."""

    result = empty_headcount_result()
    if not files:
        return result

    records: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    covered_units: set[str] = set()
    rejected_files = 0

    required_headers = {
        "atendente",
        "login",
        "grupo",
        "data inicial",
        "data final",
        "unidades de atendimento",
    }

    for uploaded_file in files:
        file_name = getattr(uploaded_file, "name", "relatorio.xlsx")
        unit_code_hint = getattr(uploaded_file, "unit_code_hint", None)
        try:
            uploaded_file.seek(0)
            raw = pd.read_excel(
                uploaded_file,
                sheet_name=0,
                header=None,
                dtype=object,
            )

            header_index: int | None = None
            for row_index, row in raw.iterrows():
                normalized_headers = {
                    normalize_identifier(value) for value in row.tolist()
                }
                if {"atendente", "login", "data final"}.issubset(
                    normalized_headers
                ):
                    header_index = int(row_index)
                    break

            if header_index is None:
                raise ValueError(
                    "Cabeçalho do Relatório de Login / Logout não encontrado."
                )

            header_positions = {
                normalize_identifier(value): position
                for position, value in enumerate(raw.iloc[header_index].tolist())
                if normalize_identifier(value)
            }
            missing = sorted(required_headers.difference(header_positions))
            if missing:
                raise ValueError(f"Colunas ausentes: {', '.join(missing)}.")

            information_cells = [
                str(value)
                for value in raw.iloc[:header_index].to_numpy().ravel()
                if normalize_identifier(value)
            ]
            issued_at = next(
                (
                    re.sub(r"^.*?:\s*", "", value)
                    for value in information_cells
                    if normalize_identifier(value).startswith("data de emissao")
                ),
                "Não informado",
            )
            period = next(
                (
                    re.sub(r"^.*?:\s*", "", value)
                    for value in information_cells
                    if normalize_identifier(value).startswith("periodo escolhido")
                ),
                "Não informado",
            )

            file_records: list[dict[str, Any]] = []
            for _, row in raw.iloc[header_index + 1 :].iterrows():
                def value(header: str) -> Any:
                    return row.iloc[header_positions[header]]

                login = report_cell_text(value("login")).lower()
                attendant = report_cell_text(value("atendente"))
                if not login or not attendant:
                    continue

                group = report_cell_text(value("grupo"))
                service_unit = report_cell_text(value("unidades de atendimento"))
                started_at = report_cell_text(value("data inicial"))
                ended_at = report_cell_text(value("data final"))
                parsed_start = pd.to_datetime(
                    started_at,
                    dayfirst=True,
                    errors="coerce",
                )
                start_order = (
                    parsed_start.to_pydatetime()
                    if not pd.isna(parsed_start)
                    else datetime.min
                )
                file_records.append(
                    {
                        "login": login,
                        "attendant": attendant,
                        "group": group,
                        "service_unit": service_unit,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "start_order": start_order,
                        "unit_code": (
                            unit_code_hint
                            or login_report_unit(f"{service_unit} {group}")
                        ),
                        "source_file": file_name,
                    }
                )

            records.extend(file_records)
            online_in_file = [
                record
                for record in file_records
                if normalize_identifier(record["ended_at"]) == "ainda online"
            ]
            distributions = sorted(
                {
                    record["unit_code"]
                    for record in file_records
                    if record["unit_code"]
                }
            )
            if unit_code_hint and unit_code_hint not in distributions:
                distributions.append(unit_code_hint)
                distributions.sort()
            covered_units.update(distributions)
            file_summaries.append(
                {
                    "Arquivo": file_name,
                    "Origem": origin,
                    "Distribuidoras": ", ".join(distributions) or "Não identificada",
                    "Registros": len(file_records),
                    "Linhas online": len(online_in_file),
                    "Emissão": issued_at,
                    "Período": period,
                    "Status": "Validado",
                }
            )
        except Exception as exc:  # mantém as consultas da API funcionando
            rejected_files += 1
            file_summaries.append(
                {
                    "Arquivo": file_name,
                    "Origem": origin,
                    "Distribuidoras": "—",
                    "Registros": 0,
                    "Linhas online": 0,
                    "Emissão": "—",
                    "Período": "—",
                    "Status": f"Inválido: {exc}",
                }
            )

    if not records and not covered_units:
        result["files"] = file_summaries
        result["warnings"] = [
            "Nenhum Relatório de Login / Logout válido foi encontrado."
        ]
        return result

    online_rows = [
        record
        for record in records
        if normalize_identifier(record["ended_at"]) == "ainda online"
    ]
    online_by_login: dict[str, dict[str, Any]] = {}
    for record in online_rows:
        current = online_by_login.get(record["login"])
        if current is None or record["start_order"] >= current["start_order"]:
            online_by_login[record["login"]] = record

    unique_online = list(online_by_login.values())
    logos_logged_today = [
        record
        for record in records
        if record["unit_code"]
        and is_logos_employee(record["login"], record["attendant"])
    ]
    checked = [
        {
            "record": record,
            "logos": is_logos_employee(record["login"], record["attendant"]),
        }
        for record in unique_online
    ]
    logos_records = [
        item["record"]
        for item in checked
        if item["logos"] and item["record"]["unit_code"]
    ]
    loaded_units = sorted(
        covered_units
        | {record["unit_code"] for record in records if record["unit_code"]}
    )
    counts: dict[str, int | None] = {
        unit.code: (0 if unit.code in loaded_units else None) for unit in UNITS
    }
    daily_counts: dict[str, int | None] = {
        unit.code: (0 if unit.code in loaded_units else None) for unit in UNITS
    }
    for unit_code in loaded_units:
        counts[unit_code] = len(
            {
                record["login"]
                for record in logos_records
                if record["unit_code"] == unit_code
            }
        )
        daily_counts[unit_code] = len(
            {
                record["login"]
                for record in logos_logged_today
                if record["unit_code"] == unit_code
            }
        )

    warnings: list[str] = []
    missing_units = [
        unit.label for unit in UNITS if unit.code not in loaded_units
    ]
    if missing_units:
        warnings.append(
            "Cobertura parcial do Login/Logout: faltam "
            + ", ".join(missing_units)
            + "."
        )
    duplicates = len(online_rows) - len(unique_online)
    if duplicates:
        warnings.append(
            f"{duplicates} registro(s) online duplicado(s) foram consolidados pelo login."
        )
    other_companies = sum(1 for item in checked if not item["logos"])
    if other_companies:
        warnings.append(
            f"{other_companies} login(s) online fora da lista Logos foram desconsiderados."
        )
    without_unit = sum(
        1
        for item in checked
        if item["logos"] and not item["record"]["unit_code"]
    )
    if without_unit:
        warnings.append(
            f"{without_unit} colaborador(es) Logos online não puderam ser associados a uma distribuidora."
        )
    if rejected_files:
        warnings.append(
            f"{rejected_files} arquivo(s) não correspondem ao formato esperado."
        )

    result.update(
        {
            "counts": counts,
            "daily_counts": daily_counts,
            "people": [
                {
                    "Login": record["login"],
                    "Nome": record["attendant"],
                    "Distribuidora": next(
                        (
                            unit.label
                            for unit in UNITS
                            if unit.code == record["unit_code"]
                        ),
                        record["unit_code"],
                    ),
                    "Grupo": record["group"],
                    "Login iniciado em": record["started_at"],
                }
                for record in sorted(
                    logos_records,
                    key=lambda item: normalize_identifier(item["attendant"]),
                )
            ],
            "files": file_summaries,
            "total_online_logins": len(unique_online),
            "logos_online": len(logos_records),
            "other_companies_online": other_companies,
            "duplicates": duplicates,
            "warnings": warnings,
            "loaded_units": loaded_units,
            "source_by_unit": {
                unit_code: origin for unit_code in loaded_units
            },
        }
    )
    return result


def merge_headcount_results(
    automatic: dict[str, Any],
    fallback: dict[str, Any],
    automatic_errors: list[str],
    expected_unit_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Prioriza a API e usa o upload somente nas unidades não cobertas."""

    merged = empty_headcount_result()
    automatic_units = set(automatic["loaded_units"])
    fallback_units = set(fallback["loaded_units"])
    expected_units = expected_unit_codes or {unit.code for unit in UNITS}

    for unit in UNITS:
        if unit.code not in expected_units:
            continue
        if unit.code in automatic_units:
            merged["counts"][unit.code] = automatic["counts"][unit.code]
            merged["daily_counts"][unit.code] = automatic["daily_counts"][
                unit.code
            ]
            merged["source_by_unit"][unit.code] = "API automática"
        elif unit.code in fallback_units:
            merged["counts"][unit.code] = fallback["counts"][unit.code]
            merged["daily_counts"][unit.code] = fallback["daily_counts"][
                unit.code
            ]
            merged["source_by_unit"][unit.code] = "Upload de contingência"

    merged["loaded_units"] = sorted(
        set(merged["source_by_unit"])
    )
    chosen_labels = {
        unit.label: unit.code for unit in UNITS
    }
    merged["people"] = [
        person
        for person in automatic["people"]
        if (
            chosen_labels.get(person["Distribuidora"]) in automatic_units
            and chosen_labels.get(person["Distribuidora"]) in expected_units
        )
    ] + [
        person
        for person in fallback["people"]
        if (
            chosen_labels.get(person["Distribuidora"]) in fallback_units
            and chosen_labels.get(person["Distribuidora"]) not in automatic_units
            and chosen_labels.get(person["Distribuidora"]) in expected_units
        )
    ]
    merged["files"] = automatic["files"] + fallback["files"]
    merged["logos_online"] = sum(
        count
        for count in merged["counts"].values()
        if count is not None
    )
    merged["total_online_logins"] = (
        automatic["total_online_logins"]
        if automatic_units
        else fallback["total_online_logins"]
    )
    merged["other_companies_online"] = (
        automatic["other_companies_online"]
        if automatic_units
        else fallback["other_companies_online"]
    )
    merged["duplicates"] = automatic["duplicates"] + fallback["duplicates"]

    warnings: list[str] = list(automatic_errors)
    warnings.extend(
        f"API automática: {warning}"
        for warning in automatic["warnings"]
        if not warning.startswith("Cobertura parcial")
    )
    warnings.extend(
        f"Upload de contingência: {warning}"
        for warning in fallback["warnings"]
        if not warning.startswith("Cobertura parcial")
    )
    missing_labels = [
        unit.label
        for unit in UNITS
        if (
            unit.code in expected_units
            and unit.code not in merged["loaded_units"]
        )
    ]
    if missing_labels:
        warnings.append(
            "Sem dados de Login/Logout para: " + ", ".join(missing_labels) + "."
        )
    merged["warnings"] = warnings
    return merged


def render_unit_overview_cards(runtime_units: list[dict[str, Any]]) -> None:
    """Exibe uma visão consolidada das distribuidoras em cartões compactos."""

    cards: list[str] = []
    for item in runtime_units:
        unit = item["unit"]
        summary = item["summary"]
        planned_hc = UNIT_PLANNED_HEADCOUNT.get(unit.code)
        planned_hc_text = "—" if planned_hc is None else str(planned_hc)
        errors = item["errors"]
        short_name = UNIT_SHORT_NAMES.get(unit.code, unit.label)
        unit_icon = UNIT_ICONS.get(unit.code, "◇")
        tma = (
            format_seconds(summary["tah_seconds"])
            if summary["tah_seconds"] is not None
            else "—"
        )
        card_class = "unit-card alert" if errors else "unit-card"
        status_class = "unit-card-status alert" if errors else "unit-card-status"
        status_text = "Com alerta" if errors else "Atualizado"
        logged_logos = summary["logged_logos"]
        logged_logos_text = "—" if logged_logos is None else str(logged_logos)
        logged_today_logos = summary["logged_today_logos"]
        logged_today_logos_text = (
            "—" if logged_today_logos is None else str(logged_today_logos)
        )
        headcount_source = summary.get("headcount_source")
        source_label = (
            "API"
            if headcount_source == "API automática"
            else "Upload"
            if headcount_source
            else "Sem dados"
        )

        cards.append(
            dedent(
                f"""
            <article class="{card_class}">
                <div class="unit-card-head">
                    <div class="unit-card-identity">
                        <span class="unit-card-symbol">{html.escape(unit_icon)}</span>
                        <div class="unit-card-title">
                            <strong>{html.escape(unit.label)}</strong>
                        </div>
                    </div>
                    <span class="{status_class}">{status_text}</span>
                </div>
                <div class="unit-card-total">
                    <div>
                        <span>Produtividade válida hoje</span>
                        <strong>{summary['total_productivity']}</strong>
                    </div>
                    <div class="unit-card-tma">
                        <span>TMA humano</span>
                        <strong>{html.escape(tma)}</strong>
                    </div>
                </div>
                <div class="unit-card-queues">
                    <div class="unit-card-queue"><span>Fila Principal - Produtividade:</span><strong>{summary['principal_total']}</strong></div>
                    <div class="unit-card-queue"><span>Ligação Nova e Troca - Produtividade:</span><strong>{summary['special_total']}</strong></div>
                </div>
                <div class="unit-card-stats">
                    <div class="unit-card-stat"><span>Atendimentos abertos</span><strong>{summary['open_count']}</strong></div>
                    <div class="unit-card-stat"><span>Fila de espera</span><strong>{summary['waiting_count']}</strong></div>
                    <div class="unit-card-stat logged"><span>Logados Atuais · {source_label}</span><strong>{logged_logos_text} / {planned_hc_text}</strong></div>
                    <div class="unit-card-stat"><span>Logaram hoje · {source_label}</span><strong>{logged_today_logos_text}</strong></div>
                    <div class="unit-card-stat carryover"><span>Iniciados ontem e finalizados hoje</span><strong>{summary['previous_day_closed']}</strong></div>
                </div>
            </article>
            """
            ).strip()
        )

    heading_html = dedent(
        """
        <div class="unit-overview-heading">
            <div>
                <h2>Volume operacional por distribuidora</h2>
                <p>Atendimentos, filas, colaboradores e TMA em uma visão consolidada.</p>
            </div>
        </div>
        """
    ).strip()
    cards_html = "".join(cards)
    st.markdown(
        f'{heading_html}\n<section class="unit-card-grid">{cards_html}</section>',
        unsafe_allow_html=True,
    )


def hourly_productivity_counts(
    records: list[dict[str, Any]],
    reference_date: date,
) -> dict[int, int]:
    """Conta por hora tickets humanos iniciados e encerrados no mesmo dia."""

    counts = {hour: 0 for hour in range(24)}
    processed_tickets: set[str] = set()

    for position, record in enumerate(records):
        username = str(
            record.get("assigned_to_username")
            or record.get("agent_username")
            or ""
        ).strip()

        if not username or username.isdigit() or "external" in username.lower():
            continue

        created_at = parse_api_datetime(record.get("created_at"))
        if not created_at:
            continue
        if created_at.astimezone(BRASILIA_TZ).date() != reference_date:
            continue

        closed_at = parse_api_datetime(record.get("closed_at"))
        if not closed_at:
            continue

        closed_local = closed_at.astimezone(BRASILIA_TZ)
        if closed_local.date() != reference_date:
            continue

        ticket_id = str(
            record.get("ticket_id")
            or record.get("protocol")
            or record.get("id")
            or record.get("uuid")
            or f"linha-{position}"
        )
        if ticket_id in processed_tickets:
            continue

        processed_tickets.add(ticket_id)
        counts[closed_local.hour] += 1

    return counts


def hourly_productivity_dataframe(
    runtime_units: list[dict[str, Any]],
    reference_date: date,
) -> pd.DataFrame:
    """Monta a produtividade por intervalo da operação selecionada."""

    general_counts = {hour: 0 for hour in range(24)}
    for item in runtime_units:
        unit_counts = item.get("hourly_productivity", {})
        for hour in range(24):
            general_counts[hour] += safe_int(unit_counts.get(hour))

    active_hours = [hour for hour, value in general_counts.items() if value]
    first_hour = min([8, *active_hours])

    now_local = datetime.now(BRASILIA_TZ)
    default_last_hour = 19
    if reference_date == now_local.date():
        default_last_hour = max(8, min(19, now_local.hour))
    last_hour = max([default_last_hour, *active_hours])
    if last_hour <= first_hour:
        if last_hour < 23:
            last_hour = first_hour + 1
        else:
            first_hour = 22

    rows: list[dict[str, Any]] = []
    for start_hour in range(first_hour, last_hour + 1):
        end_hour = start_hour + 1
        end_label = "24h" if end_hour == 24 else f"{end_hour:02d}h"
        rows.append(
            {
                "Fim": end_hour,
                "Horário": end_label,
                "Período": (
                    f"{start_hour:02d}:00 às {start_hour:02d}:59"
                ),
                "Atendimentos no período": general_counts[start_hour],
            }
        )

    return pd.DataFrame(rows)


def hourly_flow_dataframe(
    item: dict[str, Any],
    queue_name: str,
    reference_date: date,
) -> pd.DataFrame:
    """Prepara a série horária de uma distribuidora e fila para exibição."""

    raw_rows = list((item.get("hourly_queue_flow") or {}).get(queue_name) or [])
    if not raw_rows:
        return pd.DataFrame()

    active_hours = [
        int(row["hour"])
        for row in raw_rows
        if safe_int(row.get("entries")) or safe_int(row.get("exits"))
        or any(
            row.get(field) is not None
            for field in (
                "tma_seconds",
                "tme_seconds",
                "tamax_seconds",
                "temax_seconds",
            )
        )
    ]
    first_hour = min([8, *active_hours])
    now_local = datetime.now(BRASILIA_TZ)
    default_last_hour = 19
    if reference_date == now_local.date():
        default_last_hour = max(8, min(19, now_local.hour))
    last_hour = max([default_last_hour, *active_hours])

    visible_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        hour = int(row["hour"])
        if hour < first_hour or hour > last_hour:
            continue
        visible_rows.append(
            {
                "Hora": f"{hour:02d}h",
                "Período": f"{hour:02d}:00 às {hour:02d}:59",
                "Entrada": safe_int(row.get("entries")),
                "Saída": safe_int(row.get("exits")),
                "Demanda Acumulada": safe_int(row.get("accumulated_demand")),
                "Resíduo": safe_int(row.get("residue")),
                "TMA (s)": row.get("tma_seconds"),
                "TME (s)": row.get("tme_seconds"),
                "TAMAX (s)": row.get("tamax_seconds"),
                "TEMAX (s)": row.get("temax_seconds"),
            }
        )
    return pd.DataFrame(visible_rows)


def flow_time_text(value: Any) -> str:
    """Formata um tempo opcional sem transformar ausência de dado em zero."""

    if value is None or pd.isna(value):
        return "—"
    return format_seconds(value)


def render_hourly_queue_flow(
    runtime_units: list[dict[str, Any]],
    reference_date: date,
) -> None:
    """Exibe tabela e gráficos horários de volume e tempos por fila."""

    render_section_title(
        "Fluxo por hora",
        "Entrada, saída, demanda, resíduo e tempos por distribuidora e fila",
        healthy=not any(
            item["errors"].get("analytic_report") for item in runtime_units
        ),
    )
    st.caption(
        "Demanda acumulada = entrada da hora + resíduo anterior. "
        "Resíduo = máximo entre zero e demanda acumulada menos saída."
    )

    filter_columns = st.columns([1.15, 1.25, 2.6])
    unit_codes = [item["unit"].code for item in runtime_units]
    with filter_columns[0]:
        selected_unit_code = st.selectbox(
            "Distribuidora",
            options=unit_codes,
            format_func=lambda code: UNIT_SHORT_NAMES.get(code, code),
            key="hourly_flow_unit",
        )
    selected_item = next(
        item for item in runtime_units if item["unit"].code == selected_unit_code
    )
    queue_options = list((selected_item.get("hourly_queue_flow") or {}).keys())
    with filter_columns[1]:
        selected_queue = st.selectbox(
            "Fila",
            options=queue_options or ["Principal", "Ligação Nova e Troca"],
            key="hourly_flow_queue",
        )
    with filter_columns[2]:
        st.info(
            "08h representa o período de 08:00 a 08:59. Os tempos são "
            "calculados sobre os atendimentos encerrados em cada hora."
        )

    dataframe = hourly_flow_dataframe(
        selected_item,
        selected_queue,
        reference_date,
    )
    audit = selected_item.get("hourly_queue_flow_audit") or {}

    if dataframe.empty:
        st.info(
            "O relatório analítico não trouxe registros horários para esta "
            "distribuidora e fila."
        )
        return

    total_entries = int(dataframe["Entrada"].sum())
    total_exits = int(dataframe["Saída"].sum())
    current_residue = int(dataframe["Resíduo"].iloc[-1])
    peak_demand = int(dataframe["Demanda Acumulada"].max())
    metric_columns = st.columns(4)
    with metric_columns[0]:
        render_metric_card(
            "Entradas no período",
            total_entries,
            "↘",
            f"{UNIT_SHORT_NAMES.get(selected_unit_code, selected_unit_code)} · {selected_queue}",
            accent=True,
        )
    with metric_columns[1]:
        render_metric_card(
            "Saídas no período",
            total_exits,
            "↗",
            "Atendimentos encerrados",
        )
    with metric_columns[2]:
        render_metric_card(
            "Resíduo atual",
            current_residue,
            "≋",
            "Saldo acumulado sem valores negativos",
        )
    with metric_columns[3]:
        render_metric_card(
            "Pico de demanda",
            peak_demand,
            "▲",
            "Maior demanda disponível antes das saídas",
        )

    st.markdown("### Volume por hora")
    volume_rows: list[dict[str, Any]] = []
    for _, row in dataframe.iterrows():
        for series in ("Entrada", "Saída", "Demanda Acumulada", "Resíduo"):
            volume_rows.append(
                {
                    "Hora": row["Hora"],
                    "Período": row["Período"],
                    "Indicador": series,
                    "Quantidade": int(row[series]),
                }
            )
    volume_dataframe = pd.DataFrame(volume_rows)
    volume_spec = {
        "autosize": {"type": "fit", "contains": "padding", "resize": True},
        "height": 310,
        "layer": [
            {
                "transform": [
                    {"filter": "datum.Indicador == 'Entrada' || datum.Indicador == 'Saída'"}
                ],
                "mark": {"type": "bar", "cornerRadiusTopLeft": 3, "cornerRadiusTopRight": 3},
                "encoding": {
                    "x": {
                        "field": "Hora",
                        "type": "ordinal",
                        "sort": dataframe["Hora"].tolist(),
                        "title": "Hora de início do intervalo",
                        "axis": {"labelAngle": 0, "grid": False},
                    },
                    "xOffset": {"field": "Indicador"},
                    "y": {
                        "field": "Quantidade",
                        "type": "quantitative",
                        "title": "Clientes",
                        "scale": {"zero": True, "nice": True},
                    },
                    "color": {
                        "field": "Indicador",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Entrada", "Saída"],
                            "range": ["#7c3aed", "#0f9f8f"],
                        },
                    },
                    "tooltip": [
                        {"field": "Período", "type": "nominal", "title": "Período"},
                        {"field": "Indicador", "type": "nominal", "title": "Indicador"},
                        {"field": "Quantidade", "type": "quantitative", "title": "Quantidade"},
                    ],
                },
            },
            {
                "transform": [
                    {"filter": "datum.Indicador == 'Demanda Acumulada' || datum.Indicador == 'Resíduo'"}
                ],
                "mark": {"type": "line", "point": {"filled": True, "size": 48}, "strokeWidth": 2.4},
                "encoding": {
                    "x": {
                        "field": "Hora",
                        "type": "ordinal",
                        "sort": dataframe["Hora"].tolist(),
                    },
                    "y": {"field": "Quantidade", "type": "quantitative"},
                    "color": {
                        "field": "Indicador",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Demanda Acumulada", "Resíduo"],
                            "range": ["#f59e0b", "#dc2648"],
                        },
                    },
                    "strokeDash": {
                        "field": "Indicador",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Demanda Acumulada", "Resíduo"],
                            "range": [[1, 0], [7, 4]],
                        },
                    },
                    "tooltip": [
                        {"field": "Período", "type": "nominal", "title": "Período"},
                        {"field": "Indicador", "type": "nominal", "title": "Indicador"},
                        {"field": "Quantidade", "type": "quantitative", "title": "Quantidade"},
                    ],
                },
            },
        ],
        "resolve": {"scale": {"color": "independent", "strokeDash": "independent"}},
        "config": {
            "view": {"stroke": None},
            "axis": {
                "domainColor": "#dbe2ea",
                "gridColor": "#edf1f5",
                "labelColor": "#64748b",
                "titleColor": "#64748b",
            },
            "legend": {"orient": "top", "title": None},
        },
    }
    st.vega_lite_chart(volume_dataframe, volume_spec, use_container_width=True)

    st.markdown("### Tempos por hora")
    time_labels = {
        "TMA (s)": "TMA",
        "TME (s)": "TME",
        "TAMAX (s)": "TAMAX",
        "TEMAX (s)": "TEMAX",
    }
    time_rows: list[dict[str, Any]] = []
    for _, row in dataframe.iterrows():
        for source_column, indicator in time_labels.items():
            seconds = row[source_column]
            if seconds is None or pd.isna(seconds):
                continue
            time_rows.append(
                {
                    "Hora": row["Hora"],
                    "Período": row["Período"],
                    "Indicador": indicator,
                    "Minutos": float(seconds) / 60,
                    "Tempo": format_seconds(seconds),
                }
            )

    if time_rows:
        time_dataframe = pd.DataFrame(time_rows)
        time_spec = {
            "autosize": {"type": "fit", "contains": "padding", "resize": True},
            "height": 285,
            "mark": {"type": "line", "point": {"filled": True, "size": 50}, "strokeWidth": 2.4},
            "encoding": {
                "x": {
                    "field": "Hora",
                    "type": "ordinal",
                    "sort": dataframe["Hora"].tolist(),
                    "title": "Hora de encerramento",
                    "axis": {"labelAngle": 0, "grid": False},
                },
                "y": {
                    "field": "Minutos",
                    "type": "quantitative",
                    "title": "Tempo (minutos)",
                    "scale": {"zero": True, "nice": True},
                },
                "color": {
                    "field": "Indicador",
                    "type": "nominal",
                    "scale": {
                        "domain": ["TMA", "TME", "TAMAX", "TEMAX"],
                        "range": ["#7c3aed", "#0f9f8f", "#f59e0b", "#dc2648"],
                    },
                    "legend": {"title": None, "orient": "top"},
                },
                "strokeDash": {
                    "field": "Indicador",
                    "type": "nominal",
                    "scale": {
                        "domain": ["TMA", "TME", "TAMAX", "TEMAX"],
                        "range": [[1, 0], [1, 0], [7, 4], [7, 4]],
                    },
                    "legend": None,
                },
                "tooltip": [
                    {"field": "Período", "type": "nominal", "title": "Período"},
                    {"field": "Indicador", "type": "nominal", "title": "Indicador"},
                    {"field": "Tempo", "type": "nominal", "title": "Tempo"},
                ],
            },
            "config": {
                "view": {"stroke": None},
                "axis": {
                    "domainColor": "#dbe2ea",
                    "gridColor": "#edf1f5",
                    "labelColor": "#64748b",
                    "titleColor": "#64748b",
                },
            },
        }
        st.vega_lite_chart(time_dataframe, time_spec, use_container_width=True)
    else:
        st.warning(
            "A API não retornou tempos individuais de espera ou atendimento "
            "humano. Entrada, saída e resíduo continuam disponíveis."
        )

    st.markdown("### Tabela detalhada")
    table_dataframe = dataframe.copy()
    for column in time_labels:
        table_dataframe[column.removesuffix(" (s)")] = table_dataframe[column].map(
            flow_time_text
        )
    table_dataframe = table_dataframe[
        [
            "Hora",
            "Entrada",
            "Saída",
            "Demanda Acumulada",
            "Resíduo",
            "TMA",
            "TME",
            "TAMAX",
            "TEMAX",
        ]
    ]
    st.dataframe(
        table_dataframe,
        use_container_width=True,
        hide_index=True,
        height=min(610, 38 + 35 * len(table_dataframe)),
        column_config={
            "Hora": st.column_config.TextColumn("Hora", width="small"),
            "Entrada": st.column_config.NumberColumn("Entrada", format="%d"),
            "Saída": st.column_config.NumberColumn("Saída", format="%d"),
            "Demanda Acumulada": st.column_config.NumberColumn(
                "Demanda acumulada", format="%d"
            ),
            "Resíduo": st.column_config.NumberColumn("Resíduo", format="%d"),
        },
    )

    if not audit.get("available_entry_fields"):
        st.warning(
            "Não foi identificado um campo de início/criação no JSON da API. "
            "As entradas podem aparecer zeradas até o nome do campo ser mapeado."
        )
    if not audit.get("available_human_duration_fields"):
        st.caption("TMA/TAMAX: campo individual de atendimento ainda não identificado.")
    if not audit.get("available_wait_duration_fields"):
        st.caption("TME/TEMAX: campo individual de espera ainda não identificado.")


def format_integer_pt(value: int) -> str:
    """Formata inteiros com separador de milhar brasileiro."""

    return f"{value:,}".replace(",", ".")


def render_productivity_insights(
    runtime_units: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, Any]:
    """Exibe evolução horária geral e cumprimento da meta por unidade."""

    st.markdown(
        dedent(
            """
            <div class="productivity-insights-heading">
                <div>
                    <h2>Desempenho de produtividade</h2>
                    <p>
                        Evolução geral ao longo do dia e cumprimento da meta
                        por distribuidora.
                    </p>
                </div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    hourly_dataframe = hourly_productivity_dataframe(
        runtime_units,
        reference_date,
    )
    chart_spec = {
        "autosize": {
            "type": "fit",
            "contains": "padding",
            "resize": True,
        },
        "encoding": {
            "x": {
                "field": "Horário",
                "type": "nominal",
                "title": "Fim do intervalo",
                "sort": hourly_dataframe["Horário"].tolist(),
                "scale": {
                    "paddingInner": 0.55,
                    "paddingOuter": 0.25,
                },
                "axis": {
                    "labelAngle": 0,
                    "labelOverlap": "greedy",
                    "grid": False,
                },
            },
            "y": {
                "field": "Atendimentos no período",
                "type": "quantitative",
                "title": "Atendimentos encerrados",
                "scale": {"zero": True, "nice": True},
            },
            "color": {"value": "#7c3aed"},
            "tooltip": [
                {"field": "Horário", "type": "nominal", "title": "Hora"},
                {"field": "Período", "type": "nominal", "title": "Período"},
                {
                    "field": "Atendimentos no período",
                    "type": "quantitative",
                    "title": "Atendimentos",
                    "format": ",.0f",
                },
            ],
        },
        "mark": "bar",
        "height": 285,
        "background": "transparent",
        "config": {
            "view": {"stroke": None},
            "axis": {
                "domainColor": "#dbe2ea",
                "gridColor": "#edf1f5",
                "labelColor": "#64748b",
                "titleColor": "#64748b",
                "labelFontSize": 11,
                "titleFontSize": 11,
            },
            "legend": {
                "labelColor": "#475569",
                "labelFontSize": 11,
            },
        },
    }
    st.vega_lite_chart(
        hourly_dataframe,
        chart_spec,
        use_container_width=True,
    )
    st.caption(
        "Todas as barras usam o horário final do intervalo: 10h representa "
        "09:00–09:59, 11h representa 10:00–10:59, 12h representa "
        "11:00–11:59, e assim sucessivamente. Passe o mouse para ver a "
        "quantidade de atendimentos concluídos naquele período."
    )

    st.markdown(
        dedent(
            f"""
            <div class="productivity-goal-heading">
                <h3>Meta diária por distribuidora</h3>
                <p>
                    HC planejado × {DAILY_PRODUCTIVITY_PER_HC} atendimentos
                    por colaborador.
                </p>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    goal_cards: list[str] = []
    goals_diagnostic: dict[str, Any] = {}
    for item in runtime_units:
        unit = item["unit"]
        actual = safe_int(item["summary"]["total_productivity"])
        planned_hc = UNIT_PLANNED_HEADCOUNT.get(unit.code, 0)
        goal = planned_hc * DAILY_PRODUCTIVITY_PER_HC
        percentage = (actual / goal * 100) if goal else 0.0
        displayed_percentage = round(percentage)
        fill_width = min(100.0, max(0.0, percentage))
        fill_class = (
            "complete"
            if percentage >= 100
            else "warning"
            if percentage >= 75
            else ""
        )
        goal_cards.append(
            dedent(
                f"""
                <article class="productivity-goal-card">
                    <div class="productivity-goal-top">
                        <span class="productivity-goal-name">{html.escape(unit.label)}</span>
                        <strong class="productivity-goal-percent">{displayed_percentage}%</strong>
                    </div>
                    <div
                        class="productivity-goal-track"
                        role="progressbar"
                        aria-label="Meta de {html.escape(unit.label)}"
                        aria-valuenow="{min(100, displayed_percentage)}"
                        aria-valuemin="0"
                        aria-valuemax="100"
                    >
                        <div
                            class="productivity-goal-fill {fill_class}"
                            style="width: {fill_width:.2f}%"
                        ></div>
                    </div>
                    <div class="productivity-goal-detail">
                        <span>{format_integer_pt(actual)} válidos hoje</span>
                        <span>Meta {format_integer_pt(goal)}</span>
                    </div>
                </article>
                """
            ).strip()
        )
        goals_diagnostic[unit.code] = {
            "planned_headcount": planned_hc,
            "daily_goal_per_headcount": DAILY_PRODUCTIVITY_PER_HC,
            "goal": goal,
            "actual": actual,
            "percentage": round(percentage, 2),
        }

    st.markdown(
        '<section class="productivity-goal-grid">'
        + "".join(goal_cards)
        + "</section>"
        + '<p class="productivity-goal-note">'
        + "A barra visual é limitada a 100%, mas o percentual informa "
        + "resultados acima da meta."
        + "</p>",
        unsafe_allow_html=True,
    )

    return goals_diagnostic


def parse_tme_duration(value: Any) -> int | None:
    """Converte uma duração HH:MM:SS em segundos."""

    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{2,3}):([0-5]\d):([0-5]\d)", text)
    if not match:
        return None
    hours, minutes, seconds = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def format_tme_duration(total_seconds: int) -> str:
    """Formata segundos como duração HH:MM:SS."""

    safe_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(safe_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def tme_status(value_seconds: int, limit_seconds: int) -> tuple[str, str, str]:
    """Retorna classe visual, emoji e descrição do status do TME."""

    if value_seconds <= limit_seconds:
        return "below", "🟢", "Dentro do limite"
    return "above", "🔴", "Acima do limite"


def infer_tme_campaign_queues(
    campaign_ids: tuple[str, ...],
    analytic_records: list[dict[str, Any]],
) -> dict[str, str]:
    """Relaciona cada campanha à fila usando os nomes retornados pela API."""

    expected_ids = set(campaign_ids)
    queue_by_campaign: dict[str, str] = {}

    for record in analytic_records:
        campaign_id = str(record.get("campaign_id") or "").strip()
        campaign_name = str(record.get("campaign_name") or "").strip()
        if campaign_id not in expected_ids or not campaign_name:
            continue

        detected_queue = queue_label(campaign_name)
        queue_by_campaign[campaign_id] = (
            "LN-TT"
            if detected_queue == "Ligação Nova e Troca"
            else "Principal"
        )

    # Quando apenas uma campanha teve movimento, a outra necessariamente
    # representa a fila complementar da mesma distribuidora.
    if len(campaign_ids) == 2 and len(queue_by_campaign) == 1:
        identified_queue = next(iter(queue_by_campaign.values()))
        complementary_queue = (
            "Principal" if identified_queue == "LN-TT" else "LL-TT"
        )
        for campaign_id in campaign_ids:
            if campaign_id not in queue_by_campaign:
                queue_by_campaign[campaign_id] = complementary_queue

    return queue_by_campaign


def unit_tme_values(
    campaign_ids: tuple[str, ...],
    analytic_records: list[dict[str, Any]],
    campaign_results: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], dict[str, int], list[str]]:
    """Monta valores de TME por fila e informa mapeamentos pendentes."""

    queue_by_campaign = infer_tme_campaign_queues(
        campaign_ids,
        analytic_records,
    )
    values: dict[str, str] = {}
    ticket_counts: dict[str, int] = {}
    warnings: list[str] = []

    for campaign_id, result in campaign_results.items():
        queue_name = queue_by_campaign.get(campaign_id)
        if not queue_name:
            warnings.append(
                "Não foi possível identificar a fila da campanha "
                f"{campaign_id}."
            )
            continue

        wait_seconds = result.get("avg_wait_time", 0)
        values[queue_name] = format_tme_duration(round(float(wait_seconds)))
        ticket_counts[queue_name] = safe_int(result.get("total_tickets"))

    return values, ticket_counts, warnings


def render_tme_cards(
    saved_values: dict[str, dict[str, str]],
    updated_at: datetime,
    ticket_counts: dict[str, dict[str, int]] | None = None,
    automatic_distributors: set[str] | None = None,
) -> None:
    """Exibe os indicadores automáticos ou manuais por distribuidora."""

    cards: list[str] = []
    updated_text = updated_at.strftime("%H:%M")
    automatic_distributors = automatic_distributors or set()
    ticket_counts = ticket_counts or {}

    for distributor in TME_DISTRIBUTORS:
        distributor_values = saved_values.get(distributor)
        if not distributor_values:
            continue

        indicators: list[str] = []
        for queue_name, limit_text in TME_QUEUE_LIMITS.items():
            value_text = distributor_values.get(queue_name)
            if not value_text:
                continue
            value_seconds = parse_tme_duration(value_text) or 0
            limit_seconds = parse_tme_duration(limit_text) or 0
            status_class, _, status_label = tme_status(
                value_seconds,
                limit_seconds,
            )
            indicator_class = (
                "tme-indicator"
                if status_class == "below"
                else f"tme-indicator {status_class}"
            )
            dot_class = (
                "tme-dot"
                if status_class == "below"
                else f"tme-dot {status_class}"
            )
            tickets = ticket_counts.get(distributor, {}).get(queue_name)
            ticket_text = (
                f'<small class="tme-indicator-tickets">'
                f'{tickets} atendimentos no cálculo</small>'
                if tickets is not None
                else ""
            )
            indicators.append(
                dedent(
                    f"""
                    <div class="{indicator_class}" title="{html.escape(status_label)}">
                        <div class="tme-indicator-top">
                            <span class="tme-indicator-name">
                                <i class="{dot_class}"></i>
                                {html.escape(queue_name)}
                            </span>
                            <span class="tme-indicator-limit">
                                Limite: {html.escape(limit_text)}
                            </span>
                        </div>
                        <strong class="tme-indicator-value">
                            {html.escape(value_text)}
                        </strong>
                        {ticket_text}
                    </div>
                    """
                ).strip()
            )

        if not indicators:
            continue

        source_label = (
            "Mutant · automático"
            if distributor in automatic_distributors
            else "Preenchimento manual"
        )

        cards.append(
            dedent(
                f"""
                <article class="tme-unit-card">
                    <div class="tme-unit-head">
                        <strong>{html.escape(distributor)}</strong>
                        <small>{html.escape(source_label)} · {updated_text}</small>
                    </div>
                    {''.join(indicators)}
                </article>
                """
            ).strip()
        )

    st.markdown(
        '<section class="tme-card-grid">'
        + "".join(cards)
        + "</section>",
        unsafe_allow_html=True,
    )


def build_tme_whatsapp_report(
    saved_values: dict[str, dict[str, str]],
    updated_at: datetime,
) -> str:
    """Gera o relatório de TME pronto para copiar no WhatsApp."""

    lines = [
        f"💬 *Visão Geral de TME WhatsApp | {updated_at.strftime('%Hh')}*",
        "",
    ]

    available_distributors = [
        distributor
        for distributor in TME_DISTRIBUTORS
        if distributor in saved_values
    ]

    for distributor_index, distributor in enumerate(available_distributors):
        lines.extend([f"*{distributor}*", ""])
        for queue_name, limit_text in TME_QUEUE_LIMITS.items():
            value_text = saved_values[distributor].get(queue_name)
            if not value_text:
                continue
            value_seconds = parse_tme_duration(value_text) or 0
            limit_seconds = parse_tme_duration(limit_text) or 0
            _, status_emoji, _ = tme_status(value_seconds, limit_seconds)
            lines.append(
                f"{status_emoji} TME - {queue_name}: {value_text} "
                f"— Limite: {limit_text}"
            )

        if distributor_index < len(available_distributors) - 1:
            lines.extend(["-" * 50, ""])

    return "\n".join(lines)


def productivity_dataframe(
    rows: list[dict[str, Any]],
    agent_tma_values: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Normaliza e ordena as colunas exibidas na produtividade."""

    agent_tma_values = agent_tma_values or {}
    if not rows:
        return pd.DataFrame(
            columns=[
                "Login",
                "Nome",
                "Fila",
                "Encerrados",
                "TMA atual (calculado)",
            ]
        )
    dataframe = pd.DataFrame(rows)
    dataframe["TMA atual (calculado)"] = dataframe["Login"].map(
        lambda login: (
            format_seconds(agent_tma_values[str(login).strip().casefold()])
            if str(login).strip().casefold() in agent_tma_values
            else "—"
        )
    )
    preferred = [
        "Login",
        "Nome",
        "Fila",
        "Encerrados",
        "TMA atual (calculado)",
    ]
    existing = [column for column in preferred if column in dataframe.columns]
    remaining = [column for column in dataframe.columns if column not in existing]
    return dataframe[existing + remaining]


def audit_analytic_filter(
    records: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, int]:
    """Explica, em etapas exclusivas, os filtros da produtividade.

    A ordem replica ``summarize_analytic``. Cada registro é classificado em
    apenas uma exclusão ou como considerado, evitando dupla contagem.
    """

    audit = {
        "registros_recebidos": len(records),
        "sem_login": 0,
        "login_numerico": 0,
        "login_external": 0,
        "sem_data_criacao_valida": 0,
        "sem_data_encerramento_valida": 0,
        "encerrado_em_outra_data": 0,
        "iniciado_no_dia_anterior_finalizado_no_atual": 0,
        "iniciado_em_outra_data": 0,
        "ticket_duplicado": 0,
        "considerados_na_produtividade": 0,
    }
    processed_tickets: set[str] = set()

    for position, record in enumerate(records):
        username = str(
            record.get("assigned_to_username")
            or record.get("agent_username")
            or ""
        ).strip()

        if not username:
            audit["sem_login"] += 1
            continue

        if username.isdigit():
            audit["login_numerico"] += 1
            continue

        if "external" in username.lower():
            audit["login_external"] += 1
            continue

        created_at = parse_api_datetime(record.get("created_at"))
        if not created_at:
            audit["sem_data_criacao_valida"] += 1
            continue

        closed_at = parse_api_datetime(record.get("closed_at"))
        if not closed_at:
            audit["sem_data_encerramento_valida"] += 1
            continue

        closed_local = closed_at.astimezone(BRASILIA_TZ)
        if closed_local.date() != reference_date:
            audit["encerrado_em_outra_data"] += 1
            continue

        ticket_id = str(
            record.get("ticket_id")
            or record.get("protocol")
            or record.get("id")
            or record.get("uuid")
            or f"linha-{position}"
        )
        if ticket_id in processed_tickets:
            audit["ticket_duplicado"] += 1
            continue

        processed_tickets.add(ticket_id)
        created_date = created_at.astimezone(BRASILIA_TZ).date()
        if created_date == reference_date:
            audit["considerados_na_produtividade"] += 1
        elif created_date == reference_date - timedelta(days=1):
            audit["iniciado_no_dia_anterior_finalizado_no_atual"] += 1
        else:
            audit["iniciado_em_outra_data"] += 1

    return audit


inject_styles()


# ---------------------------------------------------------------------------
# Configuração lateral
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        """
        <div class="side-brand">
            <span>CO</span>
            <strong>Central Operacional</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Integração local e segura com a Mutant360")

    with st.form("monitoring_filters", clear_on_submit=False):
        st.markdown("### Acesso principal")
        st.caption("Brasília, Cosern, Elektro, Coelba e Pernambuco")
        main_username = st.text_input(
            "Usuário principal",
            placeholder="Informe o usuário principal",
        )
        main_password = st.text_input(
            "Senha principal",
            type="password",
            placeholder="Informe a senha principal",
        )

        st.divider()
        reference_date = st.date_input("Data de referência", value=date.today())
        selected_codes = st.multiselect(
            "Distribuidoras",
            options=[unit.code for unit in UNITS],
            default=[unit.code for unit in UNITS],
            format_func=lambda code: next(
                unit.label for unit in UNITS if unit.code == code
            ),
        )
        st.divider()
        st.markdown("### Contingência do HC")
        st.caption(
            "A consulta será automática. Use o upload somente se a exportação "
            "direta da Mutant falhar para alguma distribuidora."
        )
        login_logout_files = st.file_uploader(
            "Login / Logout opcional",
            type=["xlsx"],
            accept_multiple_files=True,
            help=(
                "O arquivo será usado apenas nas distribuidoras sem cobertura "
                "pela consulta automática."
            ),
        )
        run_diagnostic = st.form_submit_button(
            "Atualizar indicadores",
            type="primary",
            use_container_width=True,
        )

    st.caption("Credenciais e tokens permanecem somente nesta execução local.")
    st.caption("Atualização automática de todos os dados: a cada 10 minutos.")


monitoring_active = bool(
    run_diagnostic or st.session_state.get("monitoring_active", False)
)

render_hero(reference_date if monitoring_active else None)


if not monitoring_active:
    st.markdown(
        """
        <div class="empty-state">
            <div class="empty-icon">📈</div>
            <h3>Pronto para iniciar o monitoramento</h3>
            <p>
                Informe as credenciais na barra lateral, selecione as
                distribuidoras e pressione <strong>Atualizar indicadores</strong>.
                Nenhuma consulta acontece antes dessa confirmação.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Validação dos filtros
# ---------------------------------------------------------------------------

main_credentials_ready = bool(main_username.strip()) and bool(main_password)

validation_errors: list[str] = []
if not selected_codes:
    validation_errors.append("Selecione pelo menos uma distribuidora.")
if selected_codes and not main_credentials_ready:
    validation_errors.append("Informe o usuário e a senha principais.")

if validation_errors:
    for message in validation_errors:
        st.warning(message)
    st.stop()

if run_diagnostic:
    st.session_state["monitoring_active"] = True


# Agenda uma nova execução completa da aplicação. O fragmento desperta a cada
# dez minutos e o ``st.rerun`` refaz autenticação, consultas e cálculos de todas
# as abas sem recarregar manualmente a página no navegador.
full_refresh_key = "dashboard_last_full_refresh_at"
if run_diagnostic or not isinstance(
    st.session_state.get(full_refresh_key),
    (int, float),
):
    st.session_state[full_refresh_key] = datetime.now(BRASILIA_TZ).timestamp()


def dashboard_auto_refresh_tick() -> None:
    last_refresh = float(st.session_state.get(full_refresh_key, 0.0))
    current_time = datetime.now(BRASILIA_TZ).timestamp()
    if (
        current_time - last_refresh
        >= DASHBOARD_AUTO_REFRESH_SECONDS - AUTO_REFRESH_TOLERANCE_SECONDS
    ):
        # Atualiza o relógio antes do rerun para impedir um novo disparo
        # imediato quando a aplicação completa começar novamente.
        st.session_state[full_refresh_key] = current_time
        st.rerun()


if hasattr(st, "fragment"):
    st.fragment(
        dashboard_auto_refresh_tick,
        run_every=DASHBOARD_AUTO_REFRESH_SECONDS,
    )()


# ---------------------------------------------------------------------------
# Consultas — mesmas regras da versão funcional recebida
# ---------------------------------------------------------------------------

diagnostic_result: dict[str, Any] = {
    "executed_at": datetime.now().astimezone().isoformat(),
    "reference_date": reference_date.isoformat(),
    "units": {},
}

clients: dict[tuple[str, str], MutantClient] = {}
headcount_export_attempted: set[tuple[str, str, str]] = set()
automatic_headcount_files: list[NamedBytesIO] = []
automatic_headcount_errors: list[str] = []
selected_units = [unit for unit in UNITS if unit.code in selected_codes]
runtime_units: list[dict[str, Any]] = []

progress = st.progress(0, text="Preparando consultas...")

for index, unit in enumerate(selected_units, start=1):
    errors: dict[str, str] = {}
    ticket_stats: dict[str, Any] = {}
    human_time: dict[str, Any] = {}
    analytic_records: list[dict[str, Any]] = []
    productivity_rows: list[dict[str, Any]] = []
    individual_productivity_rows: list[dict[str, Any]] = []
    campaign_wait_times: dict[str, dict[str, Any]] = {}
    tme_values: dict[str, str] = {}
    tme_ticket_counts: dict[str, int] = {}
    tme_warnings: list[str] = []

    unit_username = main_username.strip()
    unit_password = main_password
    credential_label = "credencial principal"

    client_key = (unit.base_url, unit_username)
    authentication_ok = False

    try:
        if client_key not in clients:
            client = MutantClient(
                username=unit_username,
                password=unit_password,
                base_url=unit.base_url,
            )
            client.authenticate()
            clients[client_key] = client
        client = clients[client_key]
        authentication_ok = True
    except (MutantApiError, ValueError) as exc:
        errors["authentication"] = str(exc)

    if authentication_ok:
        for campaign_index, campaign_id in enumerate(
            unit.campaign_ids,
            start=1,
        ):
            export_key = (unit.base_url, unit_username, campaign_id)
            if export_key in headcount_export_attempted:
                continue
            headcount_export_attempted.add(export_key)
            try:
                report_content = client.login_logout_report(
                    reference_date,
                    campaign_id=campaign_id,
                )
                automatic_headcount_files.append(
                    NamedBytesIO(
                        report_content,
                        (
                            f"LoginLogout_API_{unit.code}_"
                            f"campanha_{campaign_index}_"
                            f"{reference_date.isoformat()}.xlsx"
                        ),
                        unit_code_hint=unit.code,
                    )
                )
            except MutantApiError as exc:
                automatic_headcount_errors.append(
                    f"Exportação automática em {unit.label}, "
                    f"campanha {campaign_index}: {exc}"
                )

        if unit.code == "ELEKTRO":
            # No ambiente compartilhado, a Mutant aceita as campanhas da
            # Elektro separadamente, mas rejeita as duas no mesmo payload.
            queue_names = ("Principal", "Ligação Nova e Troca")
            ticket_stats_parts: list[dict[str, Any]] = []
            ticket_stats_errors: list[str] = []

            for campaign_index, campaign_id in enumerate(unit.campaign_ids):
                queue_name = (
                    queue_names[campaign_index]
                    if campaign_index < len(queue_names)
                    else f"Campanha {campaign_index + 1}"
                )
                try:
                    ticket_stats_parts.append(
                        client.ticket_stats((campaign_id,))
                    )
                except MutantApiError as exc:
                    ticket_stats_errors.append(f"{queue_name}: {exc}")

            if ticket_stats_parts:
                ticket_stats = {
                    field: sum(
                        safe_int(part.get(field))
                        for part in ticket_stats_parts
                    )
                    for field in (
                        "open",
                        "waiting",
                        "closed",
                        "pending_from_previous_day",
                    )
                }

            if ticket_stats_errors:
                error_message = " | ".join(ticket_stats_errors)
                if ticket_stats_parts:
                    errors["ticket_stats_partial"] = (
                        "Volumetria parcial da Elektro. " + error_message
                    )
                else:
                    errors["ticket_stats"] = error_message
        else:
            try:
                ticket_stats = client.ticket_stats(unit.campaign_ids)
            except MutantApiError as exc:
                errors["ticket_stats"] = str(exc)

        try:
            human_time = client.human_service_time(
                unit.campaign_ids,
                reference_date,
            )
        except MutantApiError as exc:
            errors["human_service_time"] = str(exc)

        try:
            analytic_records = client.analytic_report(
                unit.campaign_ids,
                reference_date,
            )
            productivity_rows = summarize_analytic(
                analytic_records,
                reference_date,
            )
            individual_productivity_rows = summarize_analytic(
                analytic_records,
                reference_date,
                require_created_on_reference_date=False,
            )
        except MutantApiError as exc:
            errors["analytic_report"] = str(exc)

        tme_request_errors: list[str] = []
        for campaign_id in unit.campaign_ids:
            try:
                campaign_wait_times[campaign_id] = client.average_wait_time(
                    (campaign_id,),
                    reference_date,
                )
            except MutantApiError as exc:
                tme_request_errors.append(
                    f"campanha {campaign_id}: {exc}"
                )

        if tme_request_errors:
            errors["average_wait_time"] = " | ".join(tme_request_errors)

        tme_values, tme_ticket_counts, tme_warnings = unit_tme_values(
            unit.campaign_ids,
            analytic_records,
            campaign_wait_times,
        )
        if tme_warnings:
            mapping_warning = " | ".join(tme_warnings)
            errors["tme_campaign_mapping"] = mapping_warning

    total_productivity = sum(
        safe_int(row.get("Encerrados")) for row in productivity_rows
    )
    unique_agents = len(
        {
            str(row.get("Login"))
            for row in productivity_rows
            if str(row.get("Login") or "").strip()
        }
    )
    principal_total = sum(
        safe_int(row.get("Encerrados"))
        for row in productivity_rows
        if row.get("Fila") == "Principal"
    )
    special_total = sum(
        safe_int(row.get("Encerrados"))
        for row in productivity_rows
        if row.get("Fila") == "Ligação Nova e Troca"
    )
    individual_total_productivity = sum(
        safe_int(row.get("Encerrados")) for row in individual_productivity_rows
    )
    individual_unique_agents = len(
        {
            str(row.get("Login"))
            for row in individual_productivity_rows
            if str(row.get("Login") or "").strip()
        }
    )
    individual_principal_total = sum(
        safe_int(row.get("Encerrados"))
        for row in individual_productivity_rows
        if row.get("Fila") == "Principal"
    )
    individual_special_total = sum(
        safe_int(row.get("Encerrados"))
        for row in individual_productivity_rows
        if row.get("Fila") == "Ligação Nova e Troca"
    )
    open_count = safe_int(ticket_stats.get("open"))
    waiting_count = safe_int(ticket_stats.get("waiting"))
    closed_stats = safe_int(ticket_stats.get("closed"))
    previous_day = safe_int(ticket_stats.get("pending_from_previous_day"))
    previous_day_closed = count_previous_day_closed(
        analytic_records,
        reference_date,
    )
    tah_seconds = human_time.get("tah")
    filter_audit = audit_analytic_filter(
        analytic_records,
        reference_date,
    )
    hourly_productivity = hourly_productivity_counts(
        analytic_records,
        reference_date,
    )
    campaign_queue_map = {
        campaign_id: (
            "Principal" if campaign_index == 0 else "Ligação Nova e Troca"
        )
        for campaign_index, campaign_id in enumerate(unit.campaign_ids)
    }
    hourly_queue_flow, hourly_queue_flow_audit = build_hourly_queue_flow(
        analytic_records,
        reference_date,
        campaign_queue_map,
    )

    summary = {
        "total_productivity": total_productivity,
        "unique_agents": unique_agents,
        "principal_total": principal_total,
        "special_total": special_total,
        "individual_total_productivity": individual_total_productivity,
        "individual_unique_agents": individual_unique_agents,
        "individual_principal_total": individual_principal_total,
        "individual_special_total": individual_special_total,
        "open_count": open_count,
        "waiting_count": waiting_count,
        "closed_stats": closed_stats,
        "previous_day": previous_day,
        "previous_day_closed": previous_day_closed,
        "tah_seconds": tah_seconds,
        "logged_logos": None,
        "logged_today_logos": None,
        "tme_values": tme_values,
        "tme_ticket_counts": tme_ticket_counts,
    }

    unit_runtime = {
        "unit": unit,
        "client": client if authentication_ok else None,
        "credential_label": credential_label,
        "authentication_ok": authentication_ok,
        "ticket_stats": ticket_stats,
        "human_time": human_time,
        "analytic_records": analytic_records,
        "productivity_rows": productivity_rows,
        "individual_productivity_rows": individual_productivity_rows,
        "hourly_productivity": hourly_productivity,
        "hourly_queue_flow": hourly_queue_flow,
        "hourly_queue_flow_audit": hourly_queue_flow_audit,
        "filter_audit": filter_audit,
        "campaign_wait_times": campaign_wait_times,
        "tme_values": tme_values,
        "tme_ticket_counts": tme_ticket_counts,
        "tme_warnings": tme_warnings,
        "summary": summary,
        "errors": errors,
    }
    runtime_units.append(unit_runtime)

    diagnostic_result["units"][unit.code] = {
        "label": unit.label,
        "base_url": unit.base_url,
        "credential_type": credential_label,
        "campaign_ids": list(unit.campaign_ids),
        "ticket_stats": ticket_stats,
        "human_service_time": human_time,
        "average_wait_time_by_campaign": campaign_wait_times,
        "tme_values": tme_values,
        "tme_ticket_counts": tme_ticket_counts,
        "tme_warnings": tme_warnings,
        "analytic_record_count": len(analytic_records),
        "productivity": productivity_rows,
        "individual_productivity": individual_productivity_rows,
        "previous_day_closed_today": previous_day_closed,
        "hourly_productivity": hourly_productivity,
        "hourly_queue_flow": hourly_queue_flow,
        "hourly_queue_flow_audit": hourly_queue_flow_audit,
        "productivity_filter_audit": filter_audit,
        "logged_logos": None,
        "errors": errors,
    }

    progress.progress(
        index / len(selected_units),
        text=f"Consultando {unit.label}...",
    )

# A API é a fonte principal. O upload só preenche unidades sem cobertura.
automatic_headcount = parse_login_logout_reports(
    automatic_headcount_files,
    origin="API automática",
)
fallback_headcount = parse_login_logout_reports(
    list(login_logout_files or []),
    origin="Upload de contingência",
)
headcount_result = merge_headcount_results(
    automatic_headcount,
    fallback_headcount,
    automatic_headcount_errors,
    expected_unit_codes=set(selected_codes),
)
diagnostic_result["headcount_logos"] = headcount_result

for item in runtime_units:
    unit_code = item["unit"].code
    logged_logos = headcount_result["counts"].get(unit_code)
    logged_today_logos = headcount_result["daily_counts"].get(unit_code)
    headcount_source = headcount_result["source_by_unit"].get(unit_code)
    item["summary"]["logged_logos"] = logged_logos
    item["summary"]["logged_today_logos"] = logged_today_logos
    item["summary"]["headcount_source"] = headcount_source
    diagnostic_result["units"][unit_code]["logged_logos"] = logged_logos
    diagnostic_result["units"][unit_code]["headcount_source"] = headcount_source

progress.empty()

automatic_tme_values: dict[str, dict[str, str]] = {}
automatic_tme_ticket_counts: dict[str, dict[str, int]] = {}
automatic_tme_distributors: set[str] = set()

for item in runtime_units:
    distributor = TME_DISTRIBUTOR_BY_CODE.get(item["unit"].code)
    if not distributor:
        continue

    values = item.get("tme_values") or {}
    counts = item.get("tme_ticket_counts") or {}
    if values:
        automatic_tme_values[distributor] = dict(values)
    if counts:
        automatic_tme_ticket_counts[distributor] = dict(counts)
    if all(queue_name in values for queue_name in TME_QUEUE_LIMITS):
        automatic_tme_distributors.add(distributor)


# ---------------------------------------------------------------------------
# Navegação principal
# ---------------------------------------------------------------------------

(
    overview_tab,
    productivity_tab,
    hourly_flow_tab,
    pause_tab,
    tme_tab,
    technical_tab,
) = st.tabs(
    [
        "Visão Geral",
        "Produtividade por Atendente",
        "Fluxo por Hora",
        "Monitoramento de Pausas",
        "Relatório de TME",
        "Diagnóstico Técnico",
    ]
)


with overview_tab:
    total_productivity_all = sum(
        item["summary"]["total_productivity"] for item in runtime_units
    )
    total_open_all = sum(item["summary"]["open_count"] for item in runtime_units)
    total_waiting_all = sum(
        item["summary"]["waiting_count"] for item in runtime_units
    )
    total_agents_all = sum(
        item["summary"]["unique_agents"] for item in runtime_units
    )
    logged_values = [
        item["summary"]["logged_logos"]
        for item in runtime_units
        if item["summary"]["logged_logos"] is not None
    ]
    total_logged_logos: int | str = (
        sum(logged_values) if logged_values else "—"
    )

    render_section_title(
        "Resumo da operação",
        f"Atualizado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}",
        healthy=not any(item["errors"] for item in runtime_units),
    )

    overview_columns = st.columns(5)
    with overview_columns[0]:
        render_metric_card(
            "Produtividade total",
            total_productivity_all,
            "✓",
            "Iniciados e encerrados no dia",
            accent=True,
        )
    with overview_columns[1]:
        render_metric_card(
            "Atendimentos abertos",
            total_open_all,
            "◌",
            "Somatório das distribuidoras",
        )
    with overview_columns[2]:
        render_metric_card(
            "Em fila de espera",
            total_waiting_all,
            "⌛",
            "Aguardando atendimento",
        )
    with overview_columns[3]:
        render_metric_card(
            "Com produtividade",
            total_agents_all,
            "♟",
            "Logins com encerramento no dia",
        )
    with overview_columns[4]:
        render_metric_card(
            "Logados Logos",
            total_logged_logos,
            "●",
            (
                f"Cobertura de {len(logged_values)} distribuidora(s)"
                if logged_values
                else "Consulta automática sem cobertura"
            ),
            accent=True,
        )

    diagnostic_result["overall_productivity_goal"] = (
        render_overall_goal_card(
            safe_int(total_productivity_all),
            GENERAL_DAILY_PRODUCTIVITY_GOAL,
        )
    )

    if headcount_result["loaded_units"]:
        headcount_sources = ", ".join(
            sorted(set(headcount_result["source_by_unit"].values()))
        )
        st.caption(
            "Headcount: "
            f"{headcount_result['logos_online']} colaborador(es) Logos online "
            f"em {len(headcount_result['loaded_units'])} distribuidora(s). "
            f"Fonte: {headcount_sources}."
        )
    elif headcount_result["files"]:
        st.warning(
            "O arquivo de Login / Logout não pôde ser validado. "
            "Consulte a aba Diagnóstico Técnico."
        )
    else:
        st.warning(
            "A consulta automática do Login / Logout não trouxe cobertura. "
            "Use o upload de contingência na barra lateral e consulte o "
            "Diagnóstico Técnico."
        )

    diagnostic_result["productivity_goals"] = render_productivity_insights(
        runtime_units,
        reference_date,
    )
    diagnostic_result["hourly_productivity"] = (
        hourly_productivity_dataframe(runtime_units, reference_date).to_dict(
            orient="records"
        )
    )

    render_unit_overview_cards(runtime_units)

    units_with_errors = [item for item in runtime_units if item["errors"]]
    if units_with_errors:
        names = ", ".join(item["unit"].label for item in units_with_errors)
        st.warning(
            f"Há consultas com alerta em: {names}. "
            "Veja os detalhes na aba Diagnóstico Técnico."
        )


with productivity_tab:
    render_section_title(
        "Produtividade individual",
        "Atendimentos encerrados no dia, independentemente da data de início",
        healthy=not any(item["errors"].get("analytic_report") for item in runtime_units),
    )

    agent_tma_values = calculate_agent_tma(
        [
            record
            for item in runtime_units
            for record in item["analytic_records"]
        ],
        reference_date,
    )

    for item in runtime_units:
        unit = item["unit"]
        rows = item["individual_productivity_rows"]
        summary = item["summary"]

        st.markdown(f"### {UNIT_ICONS.get(unit.code, '📍')} {unit.label}")
        st.markdown(
            f"""
            <div class="queue-chip-row">
                <span class="queue-chip">Total: {summary['individual_total_productivity']}</span>
                <span class="queue-chip">Principal: {summary['individual_principal_total']}</span>
                <span class="queue-chip">Ligação Nova e Troca: {summary['individual_special_total']}</span>
                <span class="queue-chip">Com produtividade: {summary['individual_unique_agents']}</span>
                <span class="queue-chip">Logados Logos: {summary['logged_logos'] if summary['logged_logos'] is not None else '—'}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if rows:
            dataframe = productivity_dataframe(rows, agent_tma_values)
            st.dataframe(
                dataframe,
                use_container_width=True,
                hide_index=True,
                height=min(520, 42 + 35 * len(dataframe)),
                column_config={
                    "Login": st.column_config.TextColumn("Login", width="medium"),
                    "Nome": st.column_config.TextColumn("Nome", width="large"),
                    "Fila": st.column_config.TextColumn("Fila", width="medium"),
                    "Encerrados": st.column_config.NumberColumn(
                        "Encerrados",
                        format="%d",
                        width="small",
                    ),
                    "TMA atual (calculado)": st.column_config.TextColumn(
                        "TMA atual (calculado)",
                        width="medium",
                        help=(
                            "Média de total_agent_time dos atendimentos encerrados "
                            "no dia pelo colaborador, independentemente do início, "
                            "considerando todas as filas e distribuidoras "
                            "selecionadas."
                        ),
                    ),
                },
            )
        else:
            st.info(
                "Nenhum atendimento humano encerrado no dia foi encontrado "
                "no relatório analítico."
            )

        st.divider()


with hourly_flow_tab:
    render_hourly_queue_flow(runtime_units, reference_date)


with pause_tab:
    def pause_monitor_fragment_body() -> None:
        render_pause_monitor(runtime_units)

    if hasattr(st, "fragment"):
        st.fragment(pause_monitor_fragment_body)()
    else:
        pause_monitor_fragment_body()


with tme_tab:
    st.markdown(
        dedent(
            """
            <div class="tme-page-heading">
                <div>
                    <span class="tme-page-kicker">Integração automática</span>
                    <h2>TME por fila e distribuidora</h2>
                    <p>
                        Os tempos são consultados diretamente na Mutant por
                        campanha. O preenchimento manual fica disponível como
                        contingência.
                    </p>
                </div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    st.markdown(
        dedent(
            """
            <div class="tme-legend">
                <span class="tme-legend-item">
                    <i class="tme-dot"></i>Dentro do limite
                </span>
                <span class="tme-legend-item">
                    <i class="tme-dot above"></i>Acima do limite
                </span>
                <span class="tme-legend-note">
                    Fonte principal: Mutant360
                </span>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )

    if automatic_tme_distributors:
        st.success(
            "TME recebido automaticamente da Mutant para: "
            + ", ".join(
                distributor
                for distributor in TME_DISTRIBUTORS
                if distributor in automatic_tme_distributors
            )
            + "."
        )

    manual_tme_values = st.session_state.setdefault("tme_manual_values", {})
    missing_tme_items = [
        (distributor, queue_name)
        for distributor in TME_DISTRIBUTORS
        for queue_name in TME_QUEUE_LIMITS
        if not automatic_tme_values.get(distributor, {}).get(queue_name)
    ]

    if missing_tme_items:
        st.warning(
            "Alguns tempos não foram obtidos automaticamente. "
            "Use a contingência somente para os campos indicados abaixo."
        )
        with st.expander("Preenchimento manual de contingência", expanded=True):
            missing_distributors = [
                distributor
                for distributor in TME_DISTRIBUTORS
                if any(item[0] == distributor for item in missing_tme_items)
            ]
            entered_manual_values: dict[tuple[str, str], str] = {}

            with st.form("tme_manual_fallback_form", clear_on_submit=False):
                tme_columns = st.columns(len(missing_distributors))
                for column, distributor in zip(
                    tme_columns,
                    missing_distributors,
                ):
                    with column:
                        st.markdown(f"**{distributor}**")
                        for queue_name in TME_QUEUE_LIMITS:
                            if (distributor, queue_name) not in missing_tme_items:
                                continue
                            widget_key = (
                                "tme_fallback_"
                                + re.sub(
                                    r"[^a-z0-9]+",
                                    "_",
                                    distributor.lower(),
                                ).strip("_")
                                + "_"
                                + re.sub(
                                    r"[^a-z0-9]+",
                                    "_",
                                    queue_name.lower(),
                                ).strip("_")
                            )
                            if widget_key not in st.session_state:
                                st.session_state[widget_key] = (
                                    manual_tme_values
                                    .get(distributor, {})
                                    .get(queue_name, "00:00:00")
                                )
                            entered_manual_values[(distributor, queue_name)] = (
                                st.text_input(
                                    queue_name,
                                    key=widget_key,
                                    placeholder="00:00:00",
                                    help=(
                                        f"Limite de {queue_name}: "
                                        f"{TME_QUEUE_LIMITS[queue_name]}"
                                    ),
                                )
                            )

                save_manual_tme = st.form_submit_button(
                    "Salvar contingência e gerar relatório",
                    type="primary",
                    use_container_width=True,
                )

            if save_manual_tme:
                validation_messages: list[str] = []
                normalized_manual_values = {
                    distributor: dict(values)
                    for distributor, values in manual_tme_values.items()
                }

                for (distributor, queue_name), raw_value in (
                    entered_manual_values.items()
                ):
                    duration_seconds = parse_tme_duration(raw_value)
                    if duration_seconds is None:
                        validation_messages.append(
                            f"{distributor} / {queue_name}: "
                            "use o formato HH:MM:SS."
                        )
                        continue
                    normalized_manual_values.setdefault(distributor, {})[
                        queue_name
                    ] = format_tme_duration(duration_seconds)

                if validation_messages:
                    st.error("Não foi possível salvar a contingência.")
                    for message in validation_messages:
                        st.warning(message)
                else:
                    st.session_state["tme_manual_values"] = (
                        normalized_manual_values
                    )
                    manual_tme_values = normalized_manual_values
                    st.success("Tempos de contingência salvos.")

    effective_tme_values: dict[str, dict[str, str]] = {
        distributor: dict(values)
        for distributor, values in manual_tme_values.items()
    }
    for distributor, values in automatic_tme_values.items():
        effective_tme_values.setdefault(distributor, {}).update(values)

    complete_tme_values = {
        distributor: effective_tme_values[distributor]
        for distributor in TME_DISTRIBUTORS
        if distributor in effective_tme_values
        and all(
            queue_name in effective_tme_values[distributor]
            for queue_name in TME_QUEUE_LIMITS
        )
    }
    tme_updated_at = datetime.now(BRASILIA_TZ)

    if complete_tme_values:
        render_tme_cards(
            complete_tme_values,
            tme_updated_at,
            ticket_counts=automatic_tme_ticket_counts,
            automatic_distributors=automatic_tme_distributors,
        )

    if len(complete_tme_values) == len(TME_DISTRIBUTORS):
        tme_report = build_tme_whatsapp_report(
            complete_tme_values,
            tme_updated_at,
        )
        st.markdown(
            dedent(
                """
                <div class="tme-report-heading">
                    <h3>Reporte para WhatsApp</h3>
                    <p>
                        Use o ícone de cópia no canto superior direito do
                        bloco abaixo.
                    </p>
                </div>
                """
            ).strip(),
            unsafe_allow_html=True,
        )
        st.code(tme_report, language=None)
        st.download_button(
            "Baixar relatório em TXT",
            data=tme_report,
            file_name=(
                "relatorio_tme_"
                + tme_updated_at.strftime("%Y-%m-%d_%H-%M")
                + ".txt"
            ),
            mime="text/plain",
            use_container_width=False,
        )
    else:
        st.info(
            "O reporte completo será liberado quando LN-TT e Principal "
            "estiverem disponíveis para as cinco distribuidoras."
        )


with technical_tab:
    render_section_title(
        "Diagnóstico técnico",
        "Respostas brutas e conferências para investigação de divergências",
        healthy=not any(item["errors"] for item in runtime_units),
    )

    with st.expander(
        "Conferência do headcount Logos",
        expanded=bool(headcount_result["warnings"]),
    ):
        if headcount_result["files"]:
            st.write(
                f"**Logins online no relatório:** "
                f"{headcount_result['total_online_logins']}  "
                f"\n**Colaboradores Logos online:** "
                f"{headcount_result['logos_online']}  "
                f"\n**Logins de outras empresas desconsiderados:** "
                f"{headcount_result['other_companies_online']}"
            )
            st.dataframe(
                pd.DataFrame(headcount_result["files"]),
                use_container_width=True,
                hide_index=True,
            )
            if headcount_result["people"]:
                st.caption("Colaboradores Logos considerados como online:")
                st.dataframe(
                    pd.DataFrame(headcount_result["people"]),
                    use_container_width=True,
                    hide_index=True,
                )
            for warning in headcount_result["warnings"]:
                st.warning(warning)
        else:
            st.info("Nenhum relatório Login / Logout foi obtido pela API ou upload.")
            for warning in headcount_result["warnings"]:
                st.warning(warning)

    for item in runtime_units:
        unit = item["unit"]
        errors = item["errors"]
        summary = item["summary"]
        st.markdown(f"### {unit.label}")

        if item["authentication_ok"]:
            st.success(
                f"Autenticação concluída com a {item['credential_label']}."
            )
        else:
            st.error("A autenticação desta distribuidora não foi concluída.")

        if errors:
            for endpoint, message in errors.items():
                st.error(f"{endpoint}: {message}")
        else:
            st.success("Todas as consultas desta distribuidora foram concluídas.")

        st.caption(
            f"Encerrados no endpoint stats: {summary['closed_stats']} • "
            f"Registros analíticos recebidos: {len(item['analytic_records'])}"
        )

        with st.expander(
            "Detalhamento do filtro de produtividade",
            expanded=bool(
                summary["closed_stats"] != summary["total_productivity"]
            ),
        ):
            audit = item["filter_audit"]
            gross_difference = (
                summary["closed_stats"] - summary["total_productivity"]
            )
            audit_rows = [
                {
                    "Etapa": "Encerrados brutos no endpoint stats",
                    "Quantidade": summary["closed_stats"],
                    "Classificação": "Referência bruta",
                },
                {
                    "Etapa": "Registros recebidos no relatório analítico",
                    "Quantidade": audit["registros_recebidos"],
                    "Classificação": "Referência analítica",
                },
                {
                    "Etapa": "Excluídos — sem login de atendente",
                    "Quantidade": audit["sem_login"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Excluídos — login numérico (possível bot)",
                    "Quantidade": audit["login_numerico"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Excluídos — login contendo external",
                    "Quantidade": audit["login_external"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Excluídos — sem data de criação válida",
                    "Quantidade": audit["sem_data_criacao_valida"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Excluídos — sem encerramento válido",
                    "Quantidade": audit["sem_data_encerramento_valida"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Excluídos — encerrados em outra data",
                    "Quantidade": audit["encerrado_em_outra_data"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Excluídos — Ticket ID duplicado",
                    "Quantidade": audit["ticket_duplicado"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Finalizados hoje — iniciados no dia anterior",
                    "Quantidade": audit[
                        "iniciado_no_dia_anterior_finalizado_no_atual"
                    ],
                    "Classificação": "Contagem separada",
                },
                {
                    "Etapa": "Excluídos — iniciados em outra data",
                    "Quantidade": audit["iniciado_em_outra_data"],
                    "Classificação": "Exclusão",
                },
                {
                    "Etapa": "Produtividade válida — iniciou e encerrou hoje",
                    "Quantidade": audit["considerados_na_produtividade"],
                    "Classificação": "Resultado",
                },
                {
                    "Etapa": "Diferença: stats menos produtividade",
                    "Quantidade": gross_difference,
                    "Classificação": "Diferença entre fontes",
                },
            ]
            st.dataframe(
                pd.DataFrame(audit_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Etapa": st.column_config.TextColumn(
                        "Etapa",
                        width="large",
                    ),
                    "Quantidade": st.column_config.NumberColumn(
                        "Quantidade",
                        format="%d",
                        width="small",
                    ),
                    "Classificação": st.column_config.TextColumn(
                        "Classificação",
                        width="medium",
                    ),
                },
            )
            st.caption(
                "As exclusões do relatório analítico são aplicadas em sequência, "
                "portanto cada registro aparece em apenas uma categoria. Como o "
                "endpoint stats e o relatório analítico são fontes diferentes, "
                "a diferença bruta não precisa ser igual à soma das exclusões."
            )

        with st.expander("Resposta original das estatísticas dos tickets"):
            st.json(item["ticket_stats"] or {})

        with st.expander("Campos e amostra do relatório analítico"):
            records = item["analytic_records"]
            if records:
                st.write("Campos encontrados:")
                st.code("\n".join(sorted(records[0].keys())), language=None)
                st.caption("Amostra dos três primeiros registros:")
                st.json(records[:3])
            else:
                st.write("Nenhum registro analítico foi retornado.")

        with st.expander("Conferência do fluxo por hora"):
            flow_audit = item.get("hourly_queue_flow_audit") or {}
            st.json(flow_audit)
            st.caption(
                "Entradas usam o horário de criação do ticket. Saídas, TMA, "
                "TME, TAMAX e TEMAX usam o horário de encerramento."
            )

        st.divider()

    st.download_button(
        label="Baixar diagnóstico em JSON",
        data=json.dumps(
            diagnostic_result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        file_name=f"diagnostico_mutant_{reference_date.isoformat()}.json",
        mime="application/json",
        use_container_width=False,
    )
    st.caption(
        "O JSON não contém usuário, senha ou token. Ele pode conter nomes de colaboradores."
    )
