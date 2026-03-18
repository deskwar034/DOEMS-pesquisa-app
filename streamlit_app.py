import streamlit as st
import re
import io
import requests
import PyPDF2

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
    
    # 1. Mapeia os limites (fronteiras) de todos os atos no documento
    regex_cabecalho = re.compile(r"(?i)(?:^|\n)\s*(PORTARIA|DECRETO|RESOLUÇÃO|EDITAL|ATO|EXTRATO|INSTRUÇÃO)[^\n]+")
    cabecalhos = [(m.start(), m.group().strip()) for m in regex_cabecalho.finditer(texto_completo)]

    resultados = []
    
    for match_nome in regex_nome.finditer(texto_completo):
        pos_nome = match_nome.start()
        
        # 2. Isola o bloco exato onde o nome está (do Cabeçalho atual até o próximo)
        cabecalho_atual = None
        pos_inicio_ato = 0
        pos_fim_ato = len(texto_completo)
        
        for i, (pos_cab, texto_cab) in enumerate(cabecalhos):
            if pos_cab <= pos_nome:
                cabecalho_atual = texto_cab
                pos_inicio_ato = pos_cab
                if i + 1 < len(cabecalhos):
                    pos_fim_ato = cabecalhos[i+1][0]
            else:
                break
                
        if not cabecalho_atual:
            continue
            
        # Extrai o texto completo do ato (Cabeçalho + Corpo + Assinatura)
        ato_completo = texto_completo[pos_inicio_ato:pos_fim_ato].strip()
        
        # 3. ESTRATÉGIA HÍBRIDA (Atos Individuais vs Atos em Massa/Tabelas)
        # 3500 caracteres equivale a aprox. 1 página inteira de texto. 
        # Atos diretos são curtos. Tabelas de promoção são gigantes.
        
        if len(ato_completo) < 3500:
            # TIPO A: Ato Direto (Não aplicamos cortes de tabela para não perder contexto)
            resultados.append({
                "tipo": "direto",
                "cabecalho": cabecalho_atual,
                "texto_integral": ato_completo
            })
        else:
            # TIPO B: Ato em Massa / Tabela (Isolamos a ação e cortamos lixo da tabela)
            regex_acao = re.compile(r"(?i)(RESOLVE|RESOLVEM|DECIDE|DECRETA|TORNA PÚBLICO|CONVOCA|DESIGNAR|NOMEAR|EXONERAR|AUTORIZAR|CERTIFICA)[^\n]*?(?::|;|\n|$)")
            match_acao = regex_acao.search(ato_completo)
            
            match_nome_ato = re.search(nome_formatado, ato_completo, re.IGNORECASE)
            pos_nome_no_ato = match_nome_ato.start() if match_nome_ato else len(ato_completo)
            
            if match_acao:
                inicio_pos_acao = match_acao.end()
                texto_pos_acao = ato_completo[inicio_pos_acao:pos_nome_no_ato]
                
                padrao_inicio_tabela = r"(?i)\n\s*(?:NOME|MATR[ÍI]CULA|ORDEM|ANEXO|\d+[\.\-]?\s+(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD|BM|PM)|(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD)\s+(?:BM|PM|QOBM|QABM)|\d{1,3}\s+-\s+[A-Z])"
                match_tabela = re.search(padrao_inicio_tabela, texto_pos_acao)
                
                if match_tabela:
                    acao_texto = texto_pos_acao[:match_tabela.start()].strip()
                else:
                    acao_texto = texto_pos_acao.strip()
                    
                contexto = ato_completo[:inicio_pos_acao].strip() + "\n\n" + acao_texto
            else:
                contexto = ato_completo[:min(600, pos_nome_no_ato)].strip() + "\n[...]"
                
            # Limpeza Cirúrgica (Corta matrículas e patentes de outros militares na tabela)
            linhas = ato_completo.split('\n')
            linha_idx = 0
            for idx, l in enumerate(linhas):
                if re.search(nome_formatado, l, re.IGNORECASE):
                    linha_idx = idx
                    break
                    
            linha_bruta = linhas[linha_idx]
            if linha_idx + 1 < len(linhas):
                linha_bruta += " " + linhas[linha_idx + 1]
                
            match_nome_linha = re.search(nome_formatado, linha_bruta, re.IGNORECASE)
            if match_nome_linha:
                pos_fim_nome = match_nome_linha.end()
                texto_pos_nome = linha_bruta[pos_fim_nome:]
                match_matr = re.search(r"\d{2,3}\.?\d{3}-?\d{1,3}", texto_pos_nome)
                if match_matr:
                    linha_bruta = linha_bruta[:pos_fim_nome + match_matr.end()]
                else:
                    padrao_patente = r"(?i)(?:\d+[\.\-ºª]?\s+)?(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD)\b"
                    match_prox = re.search(padrao_patente, texto_pos_nome)
                    if match_prox:
                        linha_bruta = linha_bruta[:pos_fim_nome + match_prox.start()]

                texto_pre_nome = linha_bruta[:match_nome_linha.start()]
                padrao_patente = r"(?i)(?:\d+[\.\-ºª]?\s+)?(?:CEL|TC|MAJ|CAP|TEN|ASP|CAD|AL|SUBTEN|SGT|CB|SD)\b"
                matches_patentes = list(re.finditer(padrao_patente, texto_pre_nome))
                if matches_patentes:
                    ultima_patente = matches_patentes[-1]
                    linha_bruta = linha_bruta[ultima_patente.start():]
                    
            resultados.append({
                "tipo": "tabela",
                "cabecalho": cabecalho_atual,
                "contexto": contexto.strip(),
                "linha_dados": linha_bruta.strip()
            })
        
    # Remove resultados duplicados
    resultados_unicos = []
    chaves = set()
    for r in resultados:
        chave = r["cabecalho"] + (r.get("linha_dados", "") or r.get("texto_integral", ""))
        if chave not in chaves:
            chaves.add(chave)
            resultados_unicos.append(r)
            
    return resultados_unicos

def main():
    st.title("🔍 Monitorização DOEMS Avançada")
    st.markdown("Identifica e adapta a extração automaticamente para Atos em Massa (Tabelas) ou Atos Individuais (Corridos).")
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
                st.write("📄 A extrair texto...")
                texto_completo, total_paginas = extract_text_from_pdf(pdf_bytes)
                
                if texto_completo:
                    st.write(f"✅ Leitura concluída: {total_paginas} páginas processadas.")
                    st.write("⚙️ Analisando inteligência de blocos e formatando resultados...")
                    
                    atos_encontrados = processar_publicacao(texto_completo, nome_busca)
                    
                    if atos_encontrados:
                        status.update(label=f"Sucesso! Encontrado(s) {len(atos_encontrados)} ato(s).", state="complete", expanded=False)
                        
                        texto_exportacao = []
                        
                        for i, ato in enumerate(atos_encontrados, 1):
                            with st.expander(f"📄 Resultado {i} - {ato['cabecalho'][:50]}...", expanded=True):
                                st.markdown("**[PORTARIA E DADOS]**")
                                st.info(ato['cabecalho'])
                                
                                # EXIBIÇÃO DINÂMICA BASEADA NO TIPO DE ATO
                                if ato['tipo'] == "direto":
                                    st.markdown("**[TEXTO COMPLETO DO ATO INDIVIDUAL]**")
                                    st.write(ato['texto_integral'])
                                    
                                    texto_exportacao.append(
                                        f"=== RESULTADO {i} ===\n[CABEÇALHO]\n{ato['cabecalho']}\n\n[TEXTO COMPLETO DO ATO]\n{ato['texto_integral']}\n"
                                    )
                                else:
                                    st.markdown("**[CONTEXTO DA AÇÃO]**")
                                    st.write(ato['contexto'])
                                    
                                    st.markdown("**[NOME E DADOS DA TABELA]**")
                                    st.code(ato['linha_dados'], language="text")
                                    
                                    texto_exportacao.append(
                                        f"=== RESULTADO {i} ===\n[CABEÇALHO]\n{ato['cabecalho']}\n\n[CONTEXTO]\n{ato['contexto']}\n\n[DADOS TABELA]\n{ato['linha_dados']}\n"
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
