<#ftl output_format="plainText">
<#if freepodApp??>${msg("emailVerificationBodyApp",link, linkExpiration, realmName, linkExpirationFormatter(linkExpiration), freepodApp.label)}<#else>${msg("emailVerificationBody",link, linkExpiration, realmName, linkExpirationFormatter(linkExpiration))}</#if>
