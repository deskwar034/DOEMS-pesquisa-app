import streamlit as st
import re
import io
import requests
import PyPDF2

# Configuração da página
st.set_page_config(page_title="Buscador Regex em PDF", page_icon="🔍", layout="centered")

@st.cache_data
def extract_text_from_pdf(file_bytes):
    """Extrai todo o texto de um arquivo PDF."""
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
    st.title("🔍 Buscador Regex em PDF")
    st.markdown("Faça o upload de um arquivo PDF ou insira um link direto para extrair informações usando Expressões Regulares.")

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
                        response = requests.get(url_pdf, timeout=10)
                        response.raise_for_status() # Verifica se houve erro no download
                        pdf_bytes = response.content
                        st.success("PDF baixado com sucesso!")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Erro ao acessar o link: {e}")

    st.divider()

    # Se o PDF foi carregado (por upload ou link), mostra a seção de busca
    if pdf_bytes:
        st.subheader("Configuração da Busca")
        
        # Padrões úteis sugeridos (focados em documentos e textos legais)
        padroes_sugeridos = {
            "Personalizado": "",
            "Leis/Decretos (Ex: Lei nº 1.234)": r"(?i)(lei|decreto)\s*(nº|n°|n.)?\s*\d+[\.\d]*",
            "CPFs (Formato 000.000.000-00)": r"\d{3}\.\d{3}\.\d{3}-\d{2}",
            "E-mails": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        }
        
        escolha_padrao = st.selectbox("Escolha um padrão rápido ou use um personalizado:", list(padroes_sugeridos.keys()))
        
        # Define o regex baseado na escolha
        regex_default = padroes_sugeridos[escolha_padrao]
        padrao_regex = st.text_input("Padrão Regex:", value=regex_default)

        if st.button("Buscar no Texto", type="primary"):
            if not padrao_regex:
                st.warning("Por favor, insira um padrão Regex para buscar.")
            else:
                with st.spinner("Analisando o documento..."):
                    texto_completo = extract_text_from_pdf(pdf_bytes)
                    
                    if texto_completo:
                        try:
                            # Executa a busca regex
                            # re.IGNORECASE faz a busca ignorar maiúsculas/minúsculas
                            resultados = re.finditer(padrao_regex, texto_completo, re.IGNORECASE)
                            lista_resultados = [match.group().strip() for match in resultados]
                            
                            # Remove duplicatas mantendo a ordem (opcional)
                            lista_resultados_unicos = list(dict.fromkeys(lista_resultados))

                            if lista_resultados_unicos:
                                st.success(f"Busca concluída! Foram encontrados {len(lista_resultados_unicos)} resultados únicos.")
                                
                                # Exibe os resultados em uma lista limpa
                                for i, item in enumerate(lista_resultados_unicos, 1):
                                    st.markdown(f"**{i}.** `{item}`")
                            else:
                                st.info("A busca não retornou nenhum resultado para este padrão.")
                                
                        except re.error:
                            st.error("O padrão Regex inserido é inválido. Verifique a sintaxe.")

if __name__ == "__main__":
    main()
