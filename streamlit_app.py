import streamlit as st
import re
import io
import requests
import PyPDF2

# Configuração da página
st.set_page_config(page_title="Monitorização DOEMS", page_icon="🔍", layout="centered")

@st.cache_data
def extract_text_from_pdf(file_bytes):
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        total_pages = len(reader.pages)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text, total_pages
    except Exception as e:
        return None, str(e)

def processar_publicacao(texto_completo, nome_busca):
    nome_formatado = r"\s+".join(nome_busca.strip().split())
    regex_nome = re.compile(nome_formatado, re.IGNORECASE)
    
    regex_cabecalho = re.compile(r"(?i)(?:^|\n)\s*(PORTARIA|DECRETO|RESOLUÇÃO|EDITAL|ATO|EXTRATO)[^\n]+")
    regex_acao = re.compile(r"(?i)(RESOLVE|RESOLVEM|DECIDE|DECRETA|TORNA PÚBLICO|CONVOCA|DESIGNAR|NOMEAR|EXONERAR|AUTORIZAR|CERTIFICA)[^\n]*?(?::|;|\n|$)")

    resultados = []
    
    for match_nome in regex_nome.finditer(texto_completo):
        pos_nome_inicio = match_nome.start()
        
        texto_para_tras = texto_completo[:pos_nome_inicio]
        cabecalhos = list(regex_cabecalho.finditer(texto_para_tras))
        
        if not cabecalhos:
            continue
            
        ultimo_cabecalho = cabecalhos[-1]
        cabecalho_texto = ultimo_cabecalho.group().strip()
        pos_cabecalho = ultimo_cabecalho.start()
        
        bloco_intermediario = texto_completo[pos_cabecalho:pos_nome_inicio]
        match_acao = regex_acao.search(bloco_intermediario)
        
        if match_acao:
            inicio_pos_acao = match_acao.end()
            texto_pos_acao = bloco_intermediario[inicio_pos_acao:]
            
            padrao_inicio_tabela = r"(?i)\n\s*(?:NOME|MATR[ÍI]CULA|ORDEM|ANEXO|\d+[\.\-]?\s+(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD|BM|PM)|(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD)\s+(?:BM|PM|QOBM|QABM)|\d{1,3}\s+-\s+[A-Z])"
            match_tabela = re.search(padrao_inicio_tabela, texto_pos_acao)
            
            if match_tabela:
                acao_texto = texto_pos_acao[:match_tabela.start()].strip()
            else:
                acao_texto = texto_pos_acao.strip()
                
            contexto = bloco_intermediario[:inicio_pos_acao].strip() + "\n\n" + acao_texto
        else:
            limite = min(600, len(bloco_intermediario))
            contexto = bloco_intermediario[:limite].strip() + ("\n[...]" if len(bloco_intermediario) > limite else "")
            
        # --- LÓGICA DE LIMPEZA CIRÚRGICA DA TABELA ---
        linhas_antes = texto_para_tras.split('\n')
        linhas_depois = texto_completo[pos_nome_inicio:].split('\n')
        
        # Junta a linha actual. Puxa a linha de baixo também, caso a matrícula tenha caído para a linha seguinte
        linha_bruta = linhas_antes[-1] + linhas_depois[0]
        if len(linhas_depois) > 1:
            linha_bruta += " " + linhas_depois[1]
            
        match_nome_linha = re.search(nome_formatado, linha_bruta, re.IGNORECASE)
        
        if match_nome_linha:
            # A) Cortar o Lixo à Direita (Próximo militar colado)
            pos_fim_nome = match_nome_linha.end()
            texto_pos_nome = linha_bruta[pos_fim_nome:]
            
            # Procura a matrícula logo após o nome (Padrão MS: 509.116-021 ou 123456021)
            match_matr = re.search(r"\d{2,3}\.?\d{3}-?\d{1,3}", texto_pos_nome)
            if match_matr:
                fim_dados = pos_fim_nome + match_matr.end()
                linha_bruta = linha_bruta[:fim_dados] # Corta tudo o que vem depois da matrícula
            else:
                # Fallback: se não achar matrícula, corta na patente do próximo militar
                padrao_patente = r"(?i)(?:\d+[\.\-ºª]?\s+)?(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD)\b"
                match_prox = re.search(padrao_patente, texto_pos_nome)
                if match_prox:
                    linha_bruta = linha_bruta[:pos_fim_nome + match_prox.start()]

            # B) Cortar o Lixo à Esquerda (Militar anterior colado)
            texto_pre_nome = linha_bruta[:match_nome_linha.start()]
            padrao_patente = r"(?i)(?:\d+[\.\-ºª]?\s+)?(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD)\b"
            matches_patentes = list(re.finditer(padrao_patente, texto_pre_nome))
            
            if matches_patentes:
                ultima_patente = matches_patentes[-1] # Pega estritamente a última patente encontrada antes do nome
                linha_bruta = linha_bruta[ultima_patente.start():]
                
        linha_dados = linha_bruta.strip()
        # ----------------------------------------------
        
        resultados.append({
            "cabecalho": cabecalho_texto,
            "contexto": contexto.strip(),
            "linha_dados": linha_dados
        })
        
    resultados_unicos = []
    chaves = set()
    for r in resultados:
        chave = r["cabecalho"] + r["linha_dados"]
        if chave not in chaves:
            chaves.add(chave)
            resultados_unicos.append(r)
            
    return resultados_unicos

def main():
    st.title("🔍 Monitorização DOEMS Avançada")
    st.markdown("Extracção estruturada de actos por Cabeçalho, Contexto da Acção e Registo do Servidor.")
    st.divider()

    fonte = st.radio("Escolha a origem do PDF:", ("Carregar Ficheiro", "Ligação da Web (Link)"))
    pdf_bytes = None

    if fonte == "Carregar Ficheiro":
        arquivo_upado = st.file_uploader("Seleccione o ficheiro PDF", type=["pdf"])
        if arquivo_upado:
            pdf_bytes = arquivo_upado.read()
    else:
        url_pdf = st.text_input("Insira o link directo para o PDF:")
        if url_pdf and st.button("Descarregar PDF"):
            with st.status("A descarregar ficheiro...", expanded=True) as status:
                try:
                    response = requests.get(url_pdf, timeout=15)
                    response.raise_for_status()
                    pdf_bytes = response.content
                    status.update(label="PDF descarregado com sucesso!", state="complete", expanded=False)
                except requests.exceptions.RequestException as e:
                    status.update(label=f"Erro: {e}", state="error", expanded=True)

    if pdf_bytes:
        st.subheader("Configuração da Pesquisa")
        nome_busca = st.text_input("Nome do servidor/militar a pesquisar:", value="Geraldo Roberto Dias")
        
        if st.button("Pesquisar Publicações", type="primary"):
            if not nome_busca:
                st.warning("Insira um nome válido.")
                return

            with st.status("A processar documento...", expanded=True) as status:
                st.write("📄 A extrair texto (este processo pode demorar alguns segundos)...")
                texto_completo, total_paginas = extract_text_from_pdf(pdf_bytes)
                
                if texto_completo:
                    st.write(f"✅ Leitura concluída: {total_paginas} páginas processadas.")
                    st.write("⚙️ A realizar pesquisa estruturada e limpeza de tabelas...")
                    
                    atos_encontrados = processar_publicacao(texto_completo, nome_busca)
                    
                    if atos_encontrados:
                        status.update(label=f"Sucesso! Encontrado(s) {len(atos_encontrados)} registo(s).", state="complete", expanded=False)
                        
                        texto_exportacao = []
                        
                        for i, ato in enumerate(atos_encontrados, 1):
                            with st.expander(f"📄 Resultado {i} - {ato['cabecalho'][:50]}...", expanded=True):
                                st.markdown("**[PORTARIA E DADOS]**")
                                st.info(ato['cabecalho'])
                                
                                st.markdown("**[CONTEXTO COMPLETO]**")
                                st.write(ato['contexto'])
                                
                                st.markdown("**[NOME E DADOS DA TABELA]**")
                                st.code(ato['linha_dados'], language="text")
                            
                            texto_exportacao.append(
                                f"=== RESULTADO {i} ===\n"
                                f"[CABEÇALHO]\n{ato['cabecalho']}\n\n"
                                f"[CONTEXTO]\n{ato['contexto']}\n\n"
                                f"[DADOS TABELA]\n{ato['linha_dados']}\n"
                            )
                        
                        txt_final = "\n\n".join(texto_exportacao).encode('utf-8')
                        st.download_button(
                            label="📥 Descarregar resultados (TXT)",
                            data=txt_final,
                            file_name=f"extracao_{nome_busca.replace(' ', '_')}.txt",
                            mime="text/plain",
                        )
                    else:
                        st.write("⚠️ O nome não foi encontrado em nenhum acto formal neste documento.")
                        status.update(label="Pesquisa finalizada (sem resultados)", state="complete", expanded=True)
                else:
                    st.write("❌ Falha na leitura do PDF.")
                    status.update(label="Erro no processamento", state="error", expanded=True)

if __name__ == "__main__":
    main()
