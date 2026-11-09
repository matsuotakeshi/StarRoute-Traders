PORTNAME=	starroute-traders
DISTVERSION=	0.21.0
CATEGORIES=	games
MASTER_SITES=	# Private local distfile: preseed DISTDIR; no invented release URL.
MASTER_SITE_BACKUP=
DISTNAME=	starroute-traders-${DISTVERSION}

MAINTAINER=	ports@localhost
COMMENT=	Private StarRoute Traders standalone engine
WWW=		https://github.com/matsuotakeshi/StarRoute-Traders

LICENSE=	Private
LICENSE_NAME=	Private deployment only
LICENSE_TEXT=	Private source; no permission for public redistribution is granted by this port.
LICENSE_PERMS=	auto-accept

USES=		python:3.10+,run
NO_BUILD=	yes
NO_ARCH=	yes
SUB_LIST=	PYTHON_CMD=${PYTHON_CMD}
PLIST_SUB=	PYTHON_CMD=${PYTHON_CMD}
RUN_DEPENDS=	starroute-traders-client=${PORTVERSION}:games/starroute-traders-client
SUB_FILES=	standalone.json starroute starroute-admin starroute-maintain starroute-master starroute-sites starroute-universe pkg-message

pre-fetch:
	@test -f ${DISTDIR}/${DISTNAME}${EXTRACT_SUFX} || (${ECHO_MSG} "Preseed the private local distfile in DISTDIR"; exit 1)

do-install:
	${MKDIR} ${STAGEDIR}${PREFIX}/libexec/starroute-traders ${STAGEDIR}${PREFIX}/etc/starroute-traders ${STAGEDIR}${DOCSDIR} ${STAGEDIR}${EXAMPLESDIR}
	(cd ${WRKSRC} && ${COPYTREE_SHARE} "starroute srt_universe_generator" ${STAGEDIR}${PREFIX}/libexec/starroute-traders)
	${INSTALL_SCRIPT} ${WRKDIR}/starroute ${STAGEDIR}${PREFIX}/bin
	${INSTALL_SCRIPT} ${WRKDIR}/starroute-admin ${STAGEDIR}${PREFIX}/bin
	${INSTALL_SCRIPT} ${WRKDIR}/starroute-maintain ${STAGEDIR}${PREFIX}/bin
	${INSTALL_SCRIPT} ${WRKDIR}/starroute-master ${STAGEDIR}${PREFIX}/bin
	${INSTALL_SCRIPT} ${WRKDIR}/starroute-sites ${STAGEDIR}${PREFIX}/bin
	${INSTALL_SCRIPT} ${WRKDIR}/starroute-universe ${STAGEDIR}${PREFIX}/bin
	${INSTALL_DATA} ${WRKDIR}/standalone.json ${STAGEDIR}${PREFIX}/etc/starroute-traders/standalone.json.sample
	${INSTALL_DATA} ${WRKSRC}/examples/long-duration-template.json ${STAGEDIR}${PREFIX}/etc/starroute-traders/game.json.sample
	${INSTALL_DATA} ${WRKSRC}/examples/phase3-generator.json ${WRKSRC}/examples/industry-levels-trial.json ${WRKSRC}/examples/connected-universe-trial.json ${WRKSRC}/examples/release-world.json ${STAGEDIR}${EXAMPLESDIR}
	${INSTALL_DATA} ${WRKSRC}/PORTS_COMPLETE.md ${STAGEDIR}${DOCSDIR}

.include <bsd.port.mk>
