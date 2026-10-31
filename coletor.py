import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ARQUIVO_IPS = "impressoras.txt"
PATH_STATUS = "/web/guest/br/websys/webArch/topPage.cgi"
TIMEOUT = 8
SALVAR_HTML_BRUTO = True

CAMPOS_INFO = {
    "Nome do dispositivo": "modelo",
    "Local": "local",
    "Comentário": "comentario",
    "Nome do host": "hostname",
}

CAMPOS_STATUS = {
    "Sistema": "sistema",
    "Frasco de toner usado": "frasco_toner_usado",
    "Bandeja de entrada": "bandeja_entrada",
    "Bandeja de saída": "bandeja_saida",
}

def valor_ao_lado(soup, rotulo):
    alvo = soup.find(string=lambda s: s and s.strip() == rotulo)
    if not alvo:
        return None
    for texto in alvo.find_all_next(string=True):
        t = texto.strip().lstrip(":").strip()
        if t and t != rotulo:
            return t
    return None

def extrair_cor(soup, nomes_cor):
    alvo = soup.find(string=lambda s: s and any(n.lower() in s.lower() for n in nomes_cor))
    if not alvo:
        return {"texto": "N/A", "porcentagem": None}

    linha = alvo.find_parent("tr") or alvo.find_parent("td") or alvo.parent
    if not linha:
        return {"texto": "N/A", "porcentagem": None}

    texto_linha = linha.get_text().lower()
    if "substituir" in texto_linha or "vazio" in texto_linha or "empty" in texto_linha:
        return {"texto": "0%", "porcentagem": 5}

    imgs = linha.find_all("img") if hasattr(linha, "find_all") else []
    for img in imgs:
        src = img.get("src", "").lower()
        title = (img.get("title", "") or img.get("alt", "")).lower()
        
        if "c100" in src or "100%" in title:
            return {"texto": "100%", "porcentagem": 100}
        elif "c75" in src or "75%" in title:
            return {"texto": "75%", "porcentagem": 75}
        elif "c50" in src or "50%" in title:
            return {"texto": "50%", "porcentagem": 50}
        elif "c25" in src or "25%" in title:
            return {"texto": "25%", "porcentagem": 25}
        elif "c0" in src or "cend" in src or "0%" in title:
            return {"texto": "0%", "porcentagem": 5}

    texto_fallback = valor_ao_lado(soup, nomes_cor[0]) or "OK"
    return {"texto": texto_fallback, "porcentagem": 80}

def extrair_info_toner(soup):
    toner_c = extrair_cor(soup, ["Ciano", "Cyan"])
    toner_m = extrair_cor(soup, ["Magenta"])
    toner_y = extrair_cor(soup, ["Amarelo", "Yellow"])
    toner_k = extrair_cor(soup, ["Preto", "Black", "Toner"])

    is_color = (toner_c["porcentagem"] is not None) or (toner_m["porcentagem"] is not None) or (toner_y["porcentagem"] is not None)

    if is_color:
        texto_resumo = f"BK:{toner_k['texto']} | C:{toner_c['texto']} | M:{toner_m['texto']} | Y:{toner_y['texto']}"
        return {
            "is_color": True,
            "black": toner_k,
            "cyan": toner_c,
            "magenta": toner_m,
            "yellow": toner_y,
            "texto": texto_resumo
        }
    else:
        return {
            "is_color": False,
            "black": toner_k,
            "texto": toner_k["texto"],
            "porcentagem": toner_k["porcentagem"]
        }

def extrair_info_papel(soup):
    alvo = soup.find(string=lambda s: s and "Bandeja de entrada" in s)
    icone = "deviceStP75_16.gif"
    vazio = False
    quase_vazio = False

    if alvo:
        linha = alvo.find_parent("tr") or alvo.find_parent("td") or alvo.parent
        if linha:
            img = linha.find("img")
            if img and img.get("src"):
                src = img.get("src")
                icone = src.split("/")[-1]
                icone_lower = icone.lower()
                
                if "pend16" in icone_lower and "pnend" not in icone_lower:
                    vazio = True
                elif "pnend" in icone_lower or "p25" in icone_lower:
                    quase_vazio = True

    return icone, vazio, quase_vazio

def coletar(ip):
    resultado = {
        "ip": ip,
        "coletado_em": datetime.now().isoformat(timespec="seconds"),
        "online": False,
        "toner_info": {"is_color": False, "black": {"texto": "N/A", "porcentagem": None}, "texto": "N/A"},
        "toner": "N/A",
        "papel_icone": "deviceStP75_16.gif",
        "papel_vazio": False,
        "papel_quase_vazio": False,
        "papel_alerta": False
    }

    try:
        url = f"https://{ip}{PATH_STATUS}"
        r = requests.get(url, timeout=TIMEOUT, verify=False)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
    except requests.RequestException:
        try:
            url = f"http://{ip}{PATH_STATUS}"
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding
        except requests.RequestException as e:
            resultado["erro"] = str(e)
            return resultado

    if SALVAR_HTML_BRUTO:
        Path("html_bruto").mkdir(exist_ok=True)
        Path(f"html_bruto/{ip}.html").write_text(r.text, encoding="utf-8")

    soup = BeautifulSoup(r.text, "html.parser")
    resultado["online"] = True

    for rotulo, chave in {**CAMPOS_INFO, **CAMPOS_STATUS}.items():
        resultado[chave] = valor_ao_lado(soup, rotulo)

    toner_data = extrair_info_toner(soup)
    resultado["toner_info"] = toner_data
    resultado["toner"] = toner_data["texto"]

    icone_papel, papel_vazio, papel_quase_vazio = extrair_info_papel(soup)
    resultado["papel_icone"] = icone_papel
    resultado["papel_vazio"] = papel_vazio
    resultado["papel_quase_vazio"] = papel_quase_vazio
    resultado["papel_alerta"] = papel_vazio or papel_quase_vazio

    return resultado

def main():
    if not Path(ARQUIVO_IPS).exists():
        return

    ips = []
    with open(ARQUIVO_IPS, "r", encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if l and not l.startswith("#"):
                ip = l.split(";")[0].strip()
                ips.append(ip)

    with ThreadPoolExecutor(max_workers=10) as pool:
        resultados = list(pool.map(coletar, ips))

    Path("resultado.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

if __name__ == "__main__":
    main()