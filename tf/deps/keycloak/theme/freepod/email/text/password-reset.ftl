<#ftl output_format="plainText">
<#if freepodApp??>${msg("passwordResetBodyApp",link, linkExpiration, realmName, linkExpirationFormatter(linkExpiration), freepodApp.label)}<#else>${msg("passwordResetBody",link, linkExpiration, realmName, linkExpirationFormatter(linkExpiration))}</#if>
