import streamlit as st
import re
import io
import requests
import PyPDF2
import urllib.parse
from datetime import datetime, date
import zipfile

st.set_page_config(page_title="Radar DOEMS Avançado", page_icon="🕵️‍♂️", layout="centered")

def extract_text_from_pdf(file_bytes):
    """Extrai todo o texto do PDF sem usar cache para evitar estouro de memória no processamento em lote."""
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
    """Lógica Híbrida de Extração: Isola a publicação e define se é Ato Direto ou Tabela."""
    nome_formatado = r"\s+".join(nome_busca.strip().split())
    regex_nome = re.compile(nome_formatado, re.IGNORECASE)
    
    regex_cabecalho = re.compile(r"(?i)(?:^|\n)\s*(PORTARIA|DECRETO|RESOLUÇÃO|EDITAL|ATO|EXTRATO|INSTRUÇÃO)[^\n]+")
    cabecalhos = [(m.start(), m.group().strip()) for m in regex_cabecalho.finditer(texto_completo)]

    resultados = []
    
    for match_nome in regex_nome.finditer(texto_completo):
        pos_nome = match_nome.start()
        
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
            
        ato_completo = texto_completo[pos_inicio_ato:pos_fim_ato].strip()
        
        if len(ato_completo) < 3500:
            # TIPO A: Ato Direto
            resultados.append({
                "tipo": "direto",
                "cabecalho": cabecalho_atual,
                "texto_integral": ato_completo
            })
        else:
            # TIPO B: Ato em Massa / Tabela
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
                
            # Limpeza Cirúrgica de Tabela
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
        
    resultados_unicos = []
    chaves = set()
    for r in resultados:
        chave = r["cabecalho"] + (r.get("linha_dados", "") or r.get("texto_integral", ""))
        if chave not in chaves:
            chaves.add(chave)
            resultados_unicos.append(r)
            
    return resultados_unicos

def formatar_data(data_iso):
    try:
        obj_data = datetime.strptime(data_iso.split('T')[0], '%Y-%m-%d')
        return obj_data.strftime('%d/%m/%Y')
    except:
        return data_iso

def main():
    st.title("🕵️‍♂️ Radar DOEMS Automático")
    st.markdown("Busca um nome na base de dados oficial do Estado e gera relatórios otimizados para IA.")
    st.divider()

    st.subheader("Configuração da Busca")
    nome_busca = st.text_input("Nome completo para pesquisar (Ex: Geraldo Roberto Dias):")
    
    # Configuração de Datas (Padrão: Hoje até 8 anos atrás)
    hoje = date.today()
    try:
        oito_anos_atras = hoje.replace(year=hoje.year - 8)
    except ValueError:
        # Lida com o caso de 29 de fevereiro em anos bissextos
        oito_anos_atras = hoje.replace(year=hoje.year - 8, day=28)

    col1, col2 = st.columns(2)
    with col1:
        data_inicial = st.date_input("Data Inicial", value=oito_anos_atras, format="DD/MM/YYYY")
    with col2:
        data_final = st.date_input("Data Final", value=hoje, format="DD/MM/YYYY")

    # Validação de data
    if data_inicial > data_final:
        st.error("⚠️ A Data Inicial não pode ser posterior à Data Final.")
        busca_valida = False
    else:
        busca_valida = True

    if st.button("🔎 Buscar em todo o DOEMS", type="primary", disabled=not busca_valida):
        if not nome_busca:
            st.warning("Insira um nome válido para buscar.")
            return

        # Converte as datas para o formato esperado pela API (YYYY-MM-DD)
        data_ini_str = data_inicial.strftime("%Y-%m-%d")
        data_fim_str = data_final.strftime("%Y-%m-%d")
        
        # Requisição para a API do DOEMS
        termo_url = urllib.parse.quote_plus(nome_busca.strip())
        api_url = f"https://www.diariooficial.ms.gov.br/api/diarios/busca-diarios?tipo=1&texto={termo_url}&dataFinal={data_fim_str}&dataInicial={data_ini_str}&registrosPorPagina=500"

        with st.status("Consultando a base de dados do Governo...", expanded=True) as status:
            try:
                response = requests.get(api_url, timeout=15)
                response.raise_for_status()
                dados_api = response.json()
            except Exception as e:
                status.update(label="Erro ao conectar na API do DOEMS.", state="error", expanded=True)
                st.error(str(e))
                return
            
            paginas = dados_api.get('paginasDiario', [])
            total_registros = dados_api.get('totalDeRegistros', 0)
            
            if total_registros == 0 or not paginas:
                status.update(label="Nenhum registro encontrado.", state="complete", expanded=False)
                st.info(f"O termo '{nome_busca}' não foi encontrado no período de {data_inicial.strftime('%d/%m/%Y')} a {data_final.strftime('%d/%m/%Y')}.")
                return
            
            # Desduplicação de arquivos
            arquivos_unicos = {}
            for item in paginas:
                link = item['caminhoArquivo']
                if link not in arquivos_unicos:
                    arquivos_unicos[link] = {
                        'numero': item['numero'],
                        'data': item['dataPublicacao'],
                        'descricao': item['descricao']
                    }
            
            st.write(f"📊 Encontrados **{total_registros} ocorrências** distribuídas em **{len(arquivos_unicos)} edições** do Diário Oficial.")
            st.write("⏳ Iniciando download e análise estruturada (Isso pode demorar alguns minutos)...")
            
            progress_bar = st.progress(0)
            contador = 0
            total_arquivos = len(arquivos_unicos)
            
            relatorio_final = []

            for link_pdf, metadados in arquivos_unicos.items():
                contador += 1
                progress_bar.progress(contador / total_arquivos, text=f"Processando {contador}/{total_arquivos}: Edição {metadados['numero']}")
                
                try:
                    pdf_resp = requests.get(link_pdf, timeout=30)
                    if pdf_resp.status_code == 200:
                        texto_completo, paginas_lidas = extract_text_from_pdf(pdf_resp.content)
                        
                        if texto_completo:
                            atos_extraidos = processar_publicacao(texto_completo, nome_busca)
                            for ato in atos_extraidos:
                                ato['do_numero'] = metadados['numero']
                                ato['do_data'] = formatar_data(metadados['data'])
                                ato['do_desc'] = metadados['descricao']
                                relatorio_final.append(ato)
                except Exception as e:
                    st.warning(f"Falha ao processar a edição {metadados['numero']}: {e}")
            
            progress_bar.empty()
            status.update(label="Varredura concluída com sucesso!", state="complete", expanded=False)

        # Exibição e Geração de Exportação Otimizada (ZIP + Lotes de 30)
        if relatorio_final:
            st.success(f"Extração finalizada! Foram estruturados **{len(relatorio_final)} atos**.")
            
            # FATIAMENTO PARA INTELIGÊNCIA ARTIFICIAL (Máximo de 30 registros por arquivo)
            TAMANHO_LOTE = 30
            lotes = [relatorio_final[i:i + TAMANHO_LOTE] for i in range(0, len(relatorio_final), TAMANHO_LOTE)]
            
            # Criação do arquivo ZIP em memória
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                
                for idx_lote, lote in enumerate(lotes, 1):
                    texto_exportacao = [f"RELATÓRIO DE MONITORAMENTO: {nome_busca.upper()} - PARTE {idx_lote}", "="*50, ""]
                    
                    for i, ato in enumerate(lote, 1):
                        numero_geral = (idx_lote - 1) * TAMANHO_LOTE + i
                        
                        # --- Montagem para o Arquivo TXT ---
                        texto_exportacao.append(f"=== RESULTADO {numero_geral} | DOEMS {ato['do_numero']} ({ato['do_data']}) ===")
                        texto_exportacao.append(f"[CABEÇALHO]\n{ato['cabecalho']}\n")
                        if ato['tipo'] == "direto":
                            texto_exportacao.append(f"[TEXTO COMPLETO]\n{ato['texto_integral']}\n\n")
                        else:
                            texto_exportacao.append(f"[CONTEXTO]\n{ato['contexto']}\n")
                            texto_exportacao.append(f"[DADOS TABELA]\n{ato['linha_dados']}\n\n")
                    
                    # Salva este lote como um TXT dentro do ZIP
                    txt_conteudo = "\n".join(texto_exportacao).encode('utf-8')
                    nome_arquivo = f"dossie_{nome_busca.replace(' ', '_')}_parte_{idx_lote}.txt"
                    zip_file.writestr(nome_arquivo, txt_conteudo)

            # --- Exibição na Tela (mantém a visualização intuitiva para o usuário) ---
            for i, ato in enumerate(relatorio_final, 1):
                titulo_expander = f"📖 DOEMS nº {ato['do_numero']} ({ato['do_data']}) - {ato['cabecalho'][:40]}..."
                with st.expander(titulo_expander, expanded=False):
                    st.markdown(f"**Data de Publicação:** {ato['do_data']}")
                    st.markdown("**[PORTARIA E DADOS]**")
                    st.info(ato['cabecalho'])
                    if ato['tipo'] == "direto":
                        st.markdown("**[TEXTO COMPLETO DO ATO INDIVIDUAL]**")
                        st.write(ato['texto_integral'])
                    else:
                        st.markdown("**[CONTEXTO DA AÇÃO]**")
                        st.write(ato['contexto'])
                        st.markdown("**[NOME E DADOS DA TABELA]**")
                        st.code(ato['linha_dados'], language="text")
            
            st.divider()
            
            # Botão de Download disponibilizando o arquivo .ZIP gerado
            st.download_button(
                label=f"📥 Baixar Relatórios Fatiados para IA (.ZIP com {len(lotes)} arquivos)",
                data=zip_buffer.getvalue(),
                file_name=f"dossies_IA_{nome_busca.replace(' ', '_')}.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True
            )
        else:
            st.warning("O robô baixou os Diários, mas não conseguiu extrair os atos formatados.")

if __name__ == "__main__":
    main()
