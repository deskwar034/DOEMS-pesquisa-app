import streamlit as st
import re
import io
import requests
import PyPDF2
import pandas as pd

# Configuração da página
st.set_page_config(page_title="Monitoramento DOEMS - Regex", page_icon="🔍", layout="centered")

@st.cache_data
def extract_text_from_pdf(file_bytes):
    """Extrai todo o texto de um arquivo PDF com cache para otimizar a performance."""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text
    except Exception as e:
        st.error(f"Erro ao ler o PDF: {e}")
        return None

def main():
    st.title("🔍 Buscador Regex em Diário Oficial")
    st.markdown("Faça o upload de um arquivo PDF ou insira um link direto para extrair publicações e atos.")

    st.divider()

    # Escolha do método de entrada
    fonte = st.radio("Escolha a origem do PDF:", ("Upload de Arquivo", "Link da Web"))
    
    pdf_bytes = None

    # Lógica de Upload
    if fonte == "Upload de Arquivo":
        arquivo_upado = st.file_uploader("Selecione o arquivo PDF", type=["pdf"])
        if arquivo_upado is not None:
            pdf_bytes = arquivo_upado.read()
            
    # Lógica de Link
    else:
        url_pdf = st.text_input("Insira o link direto para o PDF:")
        if url_pdf:
            if st.button("Baixar PDF"):
                with st.spinner("Baixando arquivo..."):
                    try:
                        response = requests.get(url_pdf, timeout=15)
                        response.raise_for_status()
                        pdf_bytes = response.content
                        st.success("PDF baixado com sucesso!")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Erro ao acessar o link: {e}")

    st.divider()

    # Se o PDF foi carregado, mostra a seção de busca
    if pdf_bytes:
        st.subheader("Configuração da Busca")
        
        # Campo para digitar o nome (ex: Geraldo Roberto Dias)
        nome_busca = st.text_input("Nome do servidor/militar para buscar:", value="Geraldo Roberto Dias")
        
        if st.button("Buscar Publicações", type="primary"):
            if not nome_busca:
                st.warning("Por favor, insira um nome para buscar.")
            else:
                with st.spinner("Analisando o documento..."):
                    texto_completo = extract_text_from_pdf(pdf_bytes)
                    
                    if texto_completo:
                        try:
                            # 1. Trata os espaços no nome para lidar com quebras de linha ou espaços extras no PDF
                            nome_formatado = r"\s+".join(nome_busca.strip().split())
                            
                            # 2. Define as patentes militares comuns (incluindo Aspirante a Oficial, Tenentes, etc.)
                            patentes = r"(?:CEL|TC|MAJ|CAP|TEN|ASP(?:\s+OF)?|CAD|SUBTEN|SGT|CB|SD)"
                            
                            # 3. Monta a Regex. As chaves {} de quantificadores viram {{}} na f-string.
                            # O lookahead (?= ... ) agora procura por matrículas (5+ dígitos), datas ou as patentes abrangentes.
                            padrao_regex = fr"(?is)((?:PORTARIA|DECRETO|RESOLUÇÃO|EDITAL|ATO|EXTRATO)[^\n]*\n[\s\S]*?(?:resolve|designar|nomear|exonerar|registrar|autorizar)[\s\S]*?{nome_formatado}[\s\S]*?)(?=\n\s*(?:\d+\s+{patentes}|{patentes}\s+(?:BM|PM|QOBM)|\d+\s+\w+\s*/|\d{{5,}}|\w+\s+\d{{1,2}}/\d{{1,2}}/\d{{4}})|\n\s*(?:PORTARIA|DECRETO|RESOLUÇÃO|EDITAL|ATO|EXTRATO)|\Z)"
                            
                            # 4. Executa a busca
                            resultados = re.finditer(padrao_regex, texto_completo)
                            
                            # Extrai apenas o Grupo 1 (o bloco completo da publicação) limpando espaços em excesso nas pontas
                            lista_resultados = [match.group(1).strip() for match in resultados]
                            
                            if lista_resultados:
                                st.success(f"Busca concluída! Foram encontrados {len(lista_resultados)} atos contendo o nome.")
                                
                                # --- SEÇÃO DE EXPORTAÇÃO ---
                                # Cria um DataFrame do pandas para facilitar a geração do CSV
                                df_resultados = pd.DataFrame({"Publicação Encontrada": lista_resultados})
                                csv = df_resultados.to_csv(index=False).encode('utf-8')
                                
                                # Junta tudo em um TXT com separadores
                                txt_content = "\n\n" + "="*50 + "\n\n".join(lista_resultados) + "\n\n" + "="*50
                                txt_bytes = txt_content.encode('utf-8')

                                col1, col2 = st.columns(2)
                                with col1:
                                    st.download_button(
                                        label="📥 Baixar resultados em CSV",
                                        data=csv,
                                        file_name=f"publicacoes_{nome_busca.replace(' ', '_')}.csv",
                                        mime="text/csv",
                                    )
                                with col2:
                                    st.download_button(
                                        label="📥 Baixar resultados em TXT",
                                        data=txt_bytes,
                                        file_name=f"publicacoes_{nome_busca.replace(' ', '_')}.txt",
                                        mime="text/plain",
                                    )
                                st.divider()
                                # ---------------------------
                                
                                # Exibe os resultados na tela
                                for i, ato in enumerate(lista_resultados, 1):
                                    with st.expander(f"📄 Resultado {i} - Clique para expandir", expanded=True):
                                        st.text(ato)
                            else:
                                st.info("O nome não foi encontrado em nenhum ato com esse formato no documento atual.")
                                
                        except re.error as e:
                            st.error(f"Erro na construção da Regex: {e}")

if __name__ == "__main__":
    main()
