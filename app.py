import json
import os
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
ARQUIVO_IPS = "impressoras.txt"
ARQUIVO_RESULTADO = "resultado.json"
ARQUIVO_ABASTECIMENTOS = "abastecimentos.json"

def checar_ping(ip):
    param = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_cmd = "1000" if platform.system().lower() == "windows" else "1"
    comando = ["ping", param, "1", "-w", timeout_cmd, ip]
    
    try:
        resultado = subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ip": ip, "online": resultado.returncode == 0}
    except Exception:
        return {"ip": ip, "online": False}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def status():
    if not os.path.exists(ARQUIVO_IPS):
        return jsonify([])
    
    dados_coletados = {}
    p_res = Path(ARQUIVO_RESULTADO)
    if p_res.exists():
        try:
            for item in json.loads(p_res.read_text(encoding="utf-8")):
                dados_coletados[item.get("ip")] = item
        except Exception:
            pass

    lista = []
    with open(ARQUIVO_IPS, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha and not linha.startswith("#"):
                partes = [p.strip() for p in linha.split(";")]
                ip = partes[0]
                setor = partes[1] if len(partes) > 1 else f"IP: {ip}"
                tipo = partes[2].lower() if len(partes) > 2 else "ricoh"
                
                is_critica = False
                if len(partes) > 3 and "critica" in partes[3].lower():
                    is_critica = True
                elif any(kw in setor.upper() for kw in ["PRODUÇÃO", "PRODUCAO", "CRÍTICA", "CRITICA", "JDT", "MONTAGEM"]):
                    is_critica = True

                lista.append({
                    "ip": ip, 
                    "setor": setor, 
                    "tipo": tipo,
                    "critica": is_critica
                })
    
    def checar_item(item):
        res = checar_ping(item["ip"])
        res["setor"] = item["setor"]
        res["tipo"] = item["tipo"]
        res["critica"] = item["critica"]
        
        info = dados_coletados.get(item["ip"], {})
        res["toner"] = info.get("toner", "N/A")
        res["toner_info"] = info.get("toner_info", {})
        res["papel_vazio"] = info.get("papel_vazio", False)
        res["papel_quase_vazio"] = info.get("papel_quase_vazio", False)
        res["papel_alerta"] = info.get("papel_alerta", False) or res["papel_vazio"] or res["papel_quase_vazio"]
        res["papel_icone"] = info.get("papel_icone", "deviceStP75_16.gif")
        return res

    with ThreadPoolExecutor(max_workers=10) as executor:
        resultados = list(executor.map(checar_item, lista))
        
    return jsonify(resultados)

@app.route("/api/detalhes/<ip>")
def detalhes(ip):
    p = Path(ARQUIVO_RESULTADO)
    if not p.exists():
        return jsonify({"erro": "Arquivo resultado.json não encontrado. Execute o coletor.py."}), 404
    
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        impressora = next((item for item in dados if item.get("ip") == ip), None)
        if impressora:
            return jsonify(impressora)
        return jsonify({"erro": "Dados não encontrados no resultado.json"}), 404
    except Exception as e:
        return jsonify({"erro": f"Erro ao ler JSON: {str(e)}"}), 500

@app.route("/api/abastecimento", methods=["POST"])
def registrar_abastecimento():
    dados = request.get_json()
    if not dados or not dados.get("colaborador"):
        return jsonify({"erro": "Nome do colaborador é obrigatório."}), 400
    
    p = Path(ARQUIVO_ABASTECIMENTOS)
    historico = []
    if p.exists():
        try:
            historico = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            historico = []
            
    dados["data_hora"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    historico.insert(0, dados)
    
    p.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"sucesso": True})

@app.route("/api/abastecimentos")
def listar_abastecimentos():
    p = Path(ARQUIVO_ABASTECIMENTOS)
    if not p.exists():
        return jsonify([])
    try:
        historico = json.loads(p.read_text(encoding="utf-8"))
        return jsonify(historico)
    except Exception:
        return jsonify([])

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)