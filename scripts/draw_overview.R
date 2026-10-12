# Rebuild with: Rscript scripts/draw_overview.R
# Palette shared by the product diagram and dashboard.
library(grid)
stopifnot(dir.exists('heartdevspace')) # Run from the repository root.
out <- file.path('docs', 'images')
dir.create(out, recursive = TRUE, showWarnings = FALSE)
c <- list(ink='#243A45', muted='#61737B', line='#D5E1E5', teal='#167E7B',
          blue='#5B80AA', gold='#BA9348', purple='#8875A9',
          bluebg='#EDF3FA', tealbg='#EAF6F2', goldbg='#FBF4E8', purplebg='#F3EFF8')
box <- function(x,y,w,h,fill='white',border=c$line,r=.018) {
  grid.roundrect(x,y,w,h,r=unit(r,'snpc'),gp=gpar(fill=fill,col=border,lwd=1.3))
}
txt <- function(label,x,y,size=14,col=c$ink,font=1,just='centre') {
  grid.text(label,x,y,just=just,gp=gpar(fontfamily='Arial',fontsize=size,col=col,fontface=font,lineheight=1.3))
}
arrow_line <- function(x1,y1,x2,y2,col=c$muted) {
  grid.lines(c(x1,x2),c(y1,y2),arrow=arrow(length=unit(.09,'inches'),type='closed'),gp=gpar(col=col,lwd=1.5))
}
folder <- function(x,y,col) {
  grid.polygon(x+c(-.023,-.023,-.009,-.003,.026,.026),y+c(-.015,.02,.02,.013,.013,-.015),gp=gpar(fill='white',col=col,lwd=2))
}
server_icon <- function(x,y,col) {
  for (dy in c(-.02,0,.02)) { box(x,y+dy,.055,.015,'white',col,.004); grid.circle(x-.017,y+dy,r=.002,gp=gpar(fill=col,col=NA)) }
}
cloud <- function(x,y,col) {
  grid.circle(x+c(-.02,0,.022),y+c(0,.014,0),r=unit(c(.02,.027,.02),'snpc'),gp=gpar(fill='white',col=col,lwd=2))
  grid.rect(x,y-.008,.052,.025,gp=gpar(fill='white',col=NA));grid.lines(x+c(-.026,.027),y+c(-.02,-.02),gp=gpar(col=col,lwd=2))
}
chat <- function(x,y,col) {
  box(x,y,.064,.05,'white',col,.01)
  for (dx in c(-.016,0,.016)) grid.circle(x+dx,y,r=.003,gp=gpar(fill=col,col=NA))
  grid.lines(x+c(.018,.028,.028),y+c(-.025,-.035,-.023),gp=gpar(col=col,lwd=2))
}
draw <- function() {
  grid.newpage();grid.rect(gp=gpar(fill='white',col=NA))
  txt('YOUR COMPUTER',.057,.947,12,c$muted,2,'left')
  txt('YOUR DOMAIN',.63,.947,12,c$muted,2)
  txt('YOUR CHATGPT',.858,.947,12,c$muted,2)
  box(.285,.728,.475,.365,'#FCFDFE')
  box(.638,.728,.2,.365,c$goldbg)
  box(.855,.728,.2,.365,c$tealbg)
  x <- c(.16,.407,.638,.855)
  folder(x[1],.81,c$blue);server_icon(x[2],.81,c$purple);cloud(x[3],.81,c$gold);chat(x[4],.81,c$teal)
  for (i in 1:4) {
    txt(c('Project folders','DevSpace','HTTPS tunnel','ChatGPT')[i],x[i],.728,17,c$ink,2)
    txt(c('Files and commands','MCP + OAuth','dev.example.com','Your approved client')[i],x[i],.676,12,c$muted)
  }
  for (i in 1:3) arrow_line(x[i]+.077,.806,x[i+1]-.073,.806)
  txt('Windows account permissions',.285,.585,11,c$muted)
  txt('Cloudflare Tunnel',.638,.585,11,c$muted)
  txt('Connect / authorize',.855,.585,11,c$muted)
  # Heartbeat path supervises service, tunnel, and public endpoint.
  grid.lines(c(.407,.407,.855,.855),c(.542,.487,.487,.542),gp=gpar(col=c$teal,lwd=2))
  grid.lines(c(.407,.488,.502,.515,.531,.545,.56,.575,.655),rep(.487,9)+c(0,0,.015,-.018,.038,-.023,0,0,0),gp=gpar(col=c$teal,lwd=2))
  txt('30-second heartbeat',.277,.486,15,c$teal,2)
  # Three practical panels below the main connection.
  bx <- c(.192,.5,.808)
  fills <- c(c$bluebg,c$tealbg,c$purplebg)
  colors <- c(c$blue,c$teal,c$purple)
  for (i in 1:3) {
    box(bx[i],.241,.286,.347,fills[i])
    grid.circle(bx[i]-.104,.365,r=.021,gp=gpar(fill=colors[i],col=NA))
    txt(as.character(i),bx[i]-.104,.365,12,'white',2)
  }
  txt('Set up once',bx[1]-.063,.365,17,c$ink,2,'left')
  txt('Choose folders\nAuthorize your DNS zone\nCreate a stable hostname',bx[1],.254,14)
  txt('A local bilingual control panel',bx[1],.112,11,c$muted)
  txt('Approve access',bx[2]-.063,.365,17,c$ink,2,'left')
  txt('Add the HTTPS /mcp URL\nSelect OAuth in ChatGPT\nApprove on your own domain',bx[2],.254,14)
  txt('Credentials stored locally',bx[2],.112,11,c$muted)
  txt('Recover quietly',bx[3]-.063,.365,17,c$ink,2,'left')
  txt('Check service + tunnel + URL\nRestart failed components\nResume after Windows sign-in',bx[3],.254,14)
  txt('Startup grace + retry cooldowns',bx[3],.112,11,c$muted)
}
setwd(out) # Relative filenames also work with Windows Cairo in Unicode directories.
png('connection-overview.png',width=2200,height=1375,res=170,type='cairo',bg='white');draw();dev.off()
cairo_pdf('connection-overview.pdf',width=2200/170,height=1375/170,family='Arial')
draw();dev.off()
