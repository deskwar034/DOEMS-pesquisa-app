import streamlit as st
import re
import io
import requests
import PyPDF2
import pandas as pd

st.set_page_config(page_title="Monitoramento DOEMS", page_icon="🔍", layout="centered")

@st.cache_data
def extract_text_from_pdf(file_bytes):
    """Extrai todo o texto do PDF e retorna o texto e a contagem de páginas."""
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
    """Faz a busca reversa: acha o nome e isola o cabeçalho, o contexto e os dados da tabela."""
    # Prepara o nome para lidar com espaços extras
    nome_formatado = r"\s+".join(nome_busca.strip().split())
    regex_nome = re.compile(nome_formatado, re.IGNORECASE)
    
    # Regex para identificar os cabeçalhos das publicações
    regex_cabecalho = re.compile(r"(?i)(?:^|\n)\s*(PORTARIA|DECRETO|RESOLUÇÃO|EDITAL|ATO|EXTRATO)[^\n]+")
    
    # Regex para identificar a frase que introduz a lista/tabela
    regex_acao = re.compile(r"(?i)(RESOLVE|RESOLVEM|DECIDE|DECRETA|TORNA PÚBLICO|CONVOCA|DESIGNAR|NOMEAR|EXONERAR|AUTORIZAR)[^\n]*\n")

    resultados = []
    
    for match_nome in regex_nome.finditer(texto_completo):
        pos_nome_inicio = match_nome.start()
        
        # 1. Pega todo o texto antes do nome para achar o cabeçalho mais próximo
        texto_para_tras = texto_completo[:pos_nome_inicio]
        cabecalhos = list(regex_cabecalho.finditer(texto_para_tras))
        
        if not cabecalhos:
            continue # Se não houver cabeçalho antes do nome, ignora
            
        # Pega o ÚLTIMO cabeçalho encontrado antes do nome (o mais próximo)
        ultimo_cabecalho = cabecalhos[-1]
        cabecalho_texto = ultimo_cabecalho.group().strip()
        pos_cabecalho = ultimo_cabecalho.start()
        
        # 2. Isola o contexto (Do cabeçalho até a palavra 'RESOLVE', por exemplo)
        bloco_intermediario = texto_completo[pos_cabecalho:pos_nome_inicio]
        match_acao = regex_acao.search(bloco_intermediario)
        
        if match_acao:
            pos_acao_fim = match_acao.end()
            contexto = texto_completo[pos_cabecalho:pos_cabecalho + pos_acao_fim].strip()
        else:
            # Se não achar palavra de ação, limita a 600 caracteres para não puxar tabelas aleatórias
            limite = min(600, len(bloco_intermediario))
            contexto = bloco_intermediario[:limite].strip() + ("\n[...]" if len(bloco_intermediario) > limite else "")
            
        # 3. Isola a linha de dados do militar na tabela
        # Pega 2 linhas antes e 3 linhas depois do nome para garantir que Matrícula, Função e Nome entrem,
        # independentemente de como o PyPDF2 quebrou a tabela.
        linhas_antes = texto_para_tras.split('\n')
        linhas_depois = texto_completo[pos_nome_inicio:].split('\n')
        
        trecho_antes = "\n".join(linhas_antes[-3:]) if len(linhas_antes) >= 3 else "\n".join(linhas_antes)
        trecho_depois = "\n".join(linhas_depois[:3]) if len(linhas_depois) >= 3 else "\n".join(linhas_depois)
        
        linha_dados = (trecho_antes + trecho_depois).strip()
        
        resultados.append({
            "cabecalho": cabecalho_texto,
            "contexto": contexto,
            "linha_dados": linha_dados
        })
        
    # Remove ocorrências duplicadas (caso o nome apareça duas vezes no mesmo ato)
    resultados_unicos = []
    chaves = set()
    for r in resultados:
        chave = r["cabecalho"] + r["linha_dados"]
        if chave not in chaves:
            chaves.add(chave)
            resultados_unicos.append(r)
            
    return resultados_unicos

def main():
    st.title("🔍 Monitoramento DOEMS Avançado")
    st.markdown("Extração estruturada de atos por Cabeçalho, Contexto e Linha do Servidor.")
    st.divider()

    fonte = st.radio("Escolha a origem do PDF:", ("Upload de Arquivo", "Link da Web"))
    pdf_bytes = None

    if fonte == "Upload de Arquivo":
        arquivo_upado = st.file_uploader("Selecione o arquivo PDF", type=["pdf"])
        if arquivo_upado:
            pdf_bytes = arquivo_upado.read()
    else:
        url_pdf = st.text_input("Insira o link direto para o PDF:")
        if url_pdf and st.button("Baixar PDF"):
            with st.status("Baixando arquivo...", expanded=True) as status:
                try:
                    response = requests.get(url_pdf, timeout=15)
                    response.raise_for_status()
                    pdf_bytes = response.content
                    status.update(label="PDF baixado com sucesso!", state="complete", expanded=False)
                except requests.exceptions.RequestException as e:
                    status.update(label=f"Erro: {e}", state="error", expanded=True)

    if pdf_bytes:
        st.subheader("Configuração da Busca")
        nome_busca = st.text_input("Nome do servidor/militar para buscar:", value="Geraldo Roberto Dias")
        
        if st.button("Buscar Publicações", type="primary"):
            if not nome_busca:
                st.warning("Insira um nome válido.")
                return

            with st.status("Processando documento...", expanded=True) as status:
                st.write("📄 Extraindo texto (isso pode levar alguns segundos)...")
                texto_completo, total_paginas = extract_text_from_pdf(pdf_bytes)
                
                if texto_completo:
                    st.write(f"✅ Leitura concluída: {total_paginas} páginas processadas.")
                    st.write("⚙️ Realizando busca reversa e cruzamento de dados...")
                    
                    atos_encontrados = processar_publicacao(texto_completo, nome_busca)
                    
                    if atos_encontrados:
                        status.update(label=f"Sucesso! Encontrado(s) {len(atos_encontrados)} ato(s).", state="complete", expanded=False)
                        
                        texto_exportacao = []
                        
                        for i, ato in enumerate(atos_encontrados, 1):
                            with st.expander(f"📄 Resultado {i} - {ato['cabecalho'][:50]}...", expanded=True):
                                st.markdown("**[PORTARIA E DADOS]**")
                                st.info(ato['cabecalho'])
                                
                                st.markdown("**[CONTEXTO COMPLETO]**")
                                st.write(ato['contexto'])
                                
                                st.markdown("**[NOME E DADOS DA TABELA]**")
                                st.code(ato['linha_dados'], language="text")
                            
                            # Formata para o TXT
                            texto_exportacao.append(
                                f"=== RESULTADO {i} ===\n"
                                f"[CABEÇALHO]\n{ato['cabecalho']}\n\n"
                                f"[CONTEXTO]\n{ato['contexto']}\n\n"
                                f"[DADOS TABELA]\n{ato['linha_dados']}\n"
                            )
                        
                        txt_final = "\n\n".join(texto_exportacao).encode('utf-8')
                        st.download_button(
                            label="📥 Baixar resultados (TXT)",
                            data=txt_final,
                            file_name=f"extracao_{nome_busca.replace(' ', '_')}.txt",
                            mime="text/plain",
                        )
                    else:
                        st.write("⚠️ O nome não foi encontrado em nenhum ato formal neste documento.")
                        status.update(label="Busca finalizada (sem resultados)", state="complete", expanded=True)
                else:
                    st.write("❌ Falha na leitura do PDF.")
                    status.update(label="Erro no processamento", state="error", expanded=True)

if __name__ == "__main__":
    main()
