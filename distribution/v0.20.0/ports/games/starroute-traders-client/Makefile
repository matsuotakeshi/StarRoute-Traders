PORTNAME=	starroute-traders-client
DISTVERSION=	0.20.0
CATEGORIES=	games
MASTER_SITES=	# Private local distfile: preseed DISTDIR; no invented release URL.
MASTER_SITE_BACKUP=
DISTNAME=	starroute-traders-${DISTVERSION}

MAINTAINER=	ports@localhost
COMMENT=	Private StarRoute Traders client
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
RUN_DEPENDS=	${PYTHON_PKGNAMEPREFIX}sqlite3>0:databases/py-sqlite3@${PY_FLAVOR}
SUB_FILES=	remote.json starroute-door starroute-node pkg-message

pre-fetch:
	@test -f ${DISTDIR}/${DISTNAME}${EXTRACT_SUFX} || (${ECHO_MSG} "Preseed the private local distfile in DISTDIR"; exit 1)

do-install:
	${MKDIR} ${STAGEDIR}${PREFIX}/libexec/starroute-traders ${STAGEDIR}${PREFIX}/etc/starroute-traders
	(cd ${WRKSRC} && ${COPYTREE_SHARE} starroute_bbs ${STAGEDIR}${PREFIX}/libexec/starroute-traders)
	${INSTALL_SCRIPT} ${WRKDIR}/starroute-door ${WRKDIR}/starroute-node ${STAGEDIR}${PREFIX}/bin
	${INSTALL_DATA} ${WRKDIR}/remote.json ${STAGEDIR}${PREFIX}/etc/starroute-traders/remote.json.sample

.include <bsd.port.mk>
