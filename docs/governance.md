# Governança de Skills Customizadas

## Princípios

1. **Aprovação humana é obrigatória.** Nenhuma skill entra no repo sem OK do Felippe.
2. **Segurança antes de funcionalidade.** Scripts devem ser read-only por padrão. Secrets nunca hardcoded.
3. **Proveniência rastreável.** Toda skill deve registrar: origem, autor, data, motivo da criação.
4. **Company-agnostic.** Skills não devem conter CNPJ, UUID, senhas ou dados específicos de empresa.
5. **Um repo canônico.** `~/.hermes/custom-skills/` é a fonte de verdade. `~/.hermes/skills/` é o runtime.

## Papéis

### Hermes (Skills Lab)
- Inspeciona e audita segurança/conformidade
- Gera parecer técnico com diffs e recomendações
- Classifica e registra no `skills-registry.yaml`
- Implementa decisões aprovadas (copiar, adaptar, fazer patch)
- Mantém higiene: detecta drift, duplicatas, obsoletos

### Felippe (Governança)
- Define política e critérios de aprovação
- Aprova/rejeita skills para o repo
- Decide overlay vs. global
- Escala para review quando necessário

## Fluxo de aprovação

```
Proposta → Inspeção → Parecer → Aprovação → Instalação → Registro
   │          │          │          │           │           │
   │          │          │          │           │           └─ skills-registry.yaml
   │          │          │          │           └─ ~/.hermes/skills/
   │          │          │          └─ Felippe aprova
   │          │          └─ Hermes gera relatório
   │          └─ Hermes audita
   └─ Zip/link/ideia
```

## Critérios de aprovação

- [ ] SKILL.md com frontmatter válido
- [ ] Description ≤ 1024 chars, starts with "Use when..."
- [ ] Gatilhos de uso claros
- [ ] Passos operacionais documentados
- [ ] Pitfalls documentados
- [ ] Scripts sem hardcoded secrets
- [ ] Scripts read-only (ou com flag de confirmação para write)
- [ ] Company-agnostic (sem CNPJ/UUID hardcoded)
- [ ] Referências auto-contidas
- [ ] Proveniência registrada no registry

## Validação automática

O script `tools/validate_skill.py` verifica:
- Frontmatter YAML válido
- `name` e `description` presentes
- Description ≤ 1024 chars
- Body não-vazio
- Total ≤ 100K chars

Rodar antes de commit:
```bash
python tools/validate_skill.py skills/<category>/<name>/SKILL.md
```
