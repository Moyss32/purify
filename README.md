# Purify

O **Purify** é um protótipo local de interface para algumas operações de manutenção em Windows e Linux Debian-based. A prioridade desta versão é **não presumir sucesso**: a GUI separa operações confirmadas, falhas, estados já aplicados, itens não aplicáveis e resultados incertos.

> **Estado do projeto:** experimental. Os testes automatizados usam mocks e não alteram o sistema. Esta versão ainda não foi validada em uma matriz de VMs Windows/Linux nem distribuída como `.exe` ou `.AppImage`. Faça backup e revise a prévia; não use em máquinas críticas sem testes próprios.

## Escopo desta versão

| Plataforma | O que existe no código | Validação disponível nesta entrega |
|---|---|---|
| Windows 10/11 | Catálogo de Appx por identidade exata e desativação de serviços, incluindo itens migrados dos scripts legados | Consultas e alterações cobertas por respostas PowerShell simuladas; scan da GUI testado com estados simulados; não executado em Windows |
| Debian-based | Limpeza do cache APT, remoção do pacote `snapd` e desativação de alguns serviços systemd | Testes simulados; não executado em uma instalação Linux alvo |
| Android | Fora do escopo desta entrega | Nenhum APK/código Android incluído; veja [ANDROID_SCOPE.md](ANDROID_SCOPE.md) |

A lista é intencionalmente pequena. “Debian-based” não significa que todas as distribuições, versões, edições ou políticas corporativas foram testadas. Consulte [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md).

## Instalação para desenvolvimento

Requisitos: Python 3.10+ e Tkinter instalado.

### Windows

1. Instale Python com Tkinter.
2. Abra um terminal no diretório do projeto.
3. Execute `python purify.py`.
4. O Windows poderá mostrar UAC para iniciar a aplicação elevada. Se negar ou falhar, o Purify encerra sem operar.

### Debian-based

1. Instale Python, Tkinter, `pkexec`/Polkit e tenha um agente de autenticação gráfica da sua sessão desktop. Exemplo em Ubuntu/Debian: `sudo apt install python3 python3-tk policykit-1`; isso não garante que o agente gráfico esteja instalado/ativo.
2. Execute **como usuário normal**: `python3 purify.py`.
3. Para operações que requerem root, o executor usa `pkexec` por comando. Se não houver `pkexec` ou agente de autenticação, a operação falha com motivo claro. Não inicie a GUI inteira com `sudo`.

APT, `systemctl`, `dpkg-query`, `find` e `du` são ferramentas do próprio sistema operacional usadas pelas operações correspondentes; não são incluídas dentro do código Python. A distribuição não deve substituí-las por executáveis de origem desconhecida.

## Uso e resultado

1. Ao abrir, o Purify consulta automaticamente em segundo plano o estado de todos os itens **do catálogo conhecido**; use **Atualizar estados** para repetir a leitura. Isso não lista automaticamente todos os programas Win32 instalados e não altera o sistema.
2. Selecione explicitamente as operações.
3. Use **Pré-visualizar (Dry Run)**: a prévia consulta estado e explica ação, impacto, risco, privilégio e reversibilidade; não chama `execute()`.
4. Revise os nomes, impactos e níveis de reversibilidade no diálogo de confirmação.
5. Operações críticas exigem confirmação adicional.
6. A GUI mostra por operação `Concluído` (após verificação), `Falhou`, `Já estava aplicado`, `Não aplicável`, `Incerto` ou `Cancelado`, além do resumo do lote.

`Incerto` significa que uma alteração pode ter ocorrido, mas a verificação não conseguiu provar o estado final. Trate isso como algo a investigar, não como sucesso.

## Interface

O Purify é um aplicativo **desktop Tkinter**, não um site. A interface usa navegação por categorias, busca, seleção explícita e detalhes de risco/impacto. As decisões de visual e as referências consultadas estão em [UI_DESIGN.md](UI_DESIGN.md).

## Privilégios e segurança

- No Windows, `purify.py` usa UAC (`runas`) se o processo não estiver elevado. Não usa ExecutionPolicy Bypass como elevação.
- No Linux, comandos são passados como lista de argumentos, sem `shell=True`; `pkexec` autentica operações administrativas individualmente.
- O arquivo `~/.purify/session_backup.json` guarda os pré-estados necessários a rollback total e metadados de algumas operações não reversíveis. Diretório e arquivo recebem permissões restritas em sistemas POSIX quando possível.
- Não execute a interface em sistemas remotos sem console se a operação puder interromper a rede.
- Os scripts `debloat-win11-V.*.ps1` são legados e estão **desativados**: mostram aviso e encerram sem alterar o sistema. Não os use como alternativa à GUI.
- A elevação aumenta o impacto possível de uma falha; use somente operações compreendidas e selecionadas.

Veja [SECURITY.md](SECURITY.md) para o modelo e as limitações.

Para a lista de ações migradas e as que foram adiadas por exigirem suporte adicional, consulte [LEGACY_SCRIPT_COVERAGE.md](LEGACY_SCRIPT_COVERAGE.md).

## Reversibilidade atual

- **Serviços Windows/Linux:** rollback total é oferecido somente quando um snapshot inicial foi salvo e a restauração final confere o estado salvo.
- **Appx Windows:** reversibilidade parcial; o Purify registra os metadados e não promete reinstalação automática. Pode ser necessário usar a Microsoft Store.
- **Limpeza APT e remoção do Snap:** irreversíveis pelo Purify. A lista de snaps pode ser guardada como referência; isso não restaura o conteúdo.
- Um arquivo de pré-estado não é backup do sistema. Não substitui imagem, backup de arquivos ou ponto de restauração testado.

## Desenvolvimento e testes

Os testes usam `unittest` e mocks; não invocam ações reais de manutenção:

```bash
python3 -m unittest discover -v
python3 -m compileall -q .
```

Ao adicionar uma operação, implemente consulta de estado estruturada, aplicabilidade, estado-alvo, pré-estado quando houver rollback, executor com argumentos seguros e testes para sucesso/falha/estado desconhecido. O gerenciador não considera código de saída zero ou ausência de stderr como prova suficiente.

## Empacotamento

Ainda não há binários `.exe`/`.AppImage` validados nesta entrega. Consulte [BUILDING.md](BUILDING.md) para instruções de build; o build de Windows requer Windows, e AppImage deve ser testado em cada baseline suportado.
