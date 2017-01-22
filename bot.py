#!/usr/bin/env python
#-*- coding: utf-8 -*- 
# 
#    This file is part of maillist_telegram_bot.
#
#    maillist_telegram_bot is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    maillist_telegram_bot is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with maillist_telegram_bot.  If not, see <http://www.gnu.org/licenses/>.

import sys
import time
import re
import pickle
import os.path
import telepot
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from pprint import pprint
import urllib
import datetime


import dropbox
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError, AuthError


#####
## Start of configuration
#####

debug = False # This variable indicates if the current deployment uses the main bot.
BOT_NAME='@name_of_your_bot'
DEBUGBOT_NAME='@name_of_your_debugging_bot'

creator_list =[1]  # ID of the users that will have access to the dashboard
admin_list = [1,2] # ID of the users that will be able to modify the list

INACTIVE_USER_DAYS=7
DAYS_BETWEEN_PURGE=1
PERSISTENT_FILE='tmp_persistence_1_new.dat'

group_membership=12312321 # Group ID where the users must have joint before talking to the bot
rules_msg = u'Mensaje mostrado al imprimir la lista en el chat individual'
ghelp_msg = u'Mensaje de ayuda al hablar con el bot por el grupo'
help_msg = u'Mensaje de ayuda al hablar con el bot en privado\n'

not_configured = True # Change me to False.

token_deploy='CADENA CON EL TOKEN QUE CORRESPONDA SEGUN LA PLATAFORMA (TELEGRAM)'
token_debug='CADENA CON EL TOKEN QUE CORRESPONDA SEGUN LA PLATAFORMA (TELEGRAM)'
token_dropbox='CADENA CON EL TOKEN QUE CORRESPONDA SEGUN LA PLATAFORMA (DROPBOX)'

if not_configured:
  print 'You must provided some basic parameters before running me! Edit the code before'
  sys.exit(-1);


#####
## End of configuration
#####



vector_dict = {}
if debug==False:
  name_bot=BOT_NAME
  TOKEN=token_deploy #Deploy  
else:
  name_bot=DEBUGBOT_NAME
  TOKEN=token_debug
  

MESSAGE_WIDTH = 4096
INACTIVE_TIME=60
admin_is_editing_group=False
group_being_moderated=False
dashboard_options=['Print', 'Individual Group', 'Statistics', 'Quit']
ptime = datetime.datetime.now()




def remove_inactive_users(data_obj, threshold_time):
  if debug == True:
    print "I am going to purge the users"
  for k in [k for k,v in data_obj.iteritems() if v['timestamp']<threshold_time]:
    data_obj.pop(k)

def print_list_of_emails(chat_id, msg, vector_dict, bot):
  email_chain = ''

  list_of_chains = []
  for user in vector_dict:
    if len(vector_dict[user]["mail"]) >=1:
      string_to_insert = ','.join(vector_dict[user]["mail"])

      if(len(email_chain)+len(string_to_insert)+1 >= MESSAGE_WIDTH-len(rules_msg)):
        list_of_chains.append(email_chain)
        email_chain = ''

      if len(email_chain):
        email_chain=email_chain+','+string_to_insert
      else:
        email_chain=string_to_insert
 
  if len(email_chain):
    list_of_chains.append(email_chain)
  
  if len(list_of_chains):
    first_msg  = list_of_chains[0] 
    list_of_chains[0] = rules_msg+first_msg
  else:
    list_of_chains.append(rules_msg)

  if len(list_of_chains):  
    for chain in list_of_chains:    
      reply_m = bot.sendMessage(chat_id, chain, disable_notification=True)
  

def dump_to_file(obj,file_name):
  dump_file = open(file_name, 'wb')
  pickle.dump(obj, dump_file)
  dump_file.close()
  if debug==False:
    with open(file_name, 'rb') as f:
        # We use WriteMode=overwrite to make sure that the settings in the file
        # are changed on upload
        try:
            dbx.files_upload(f.read(), "/cozybot_list/"+file_name, mode=WriteMode('overwrite'))
        except ApiError as err:
            # This checks for the specific error where a user doesn't have
            # enough Dropbox space quota to upload this file
            if (err.error.is_path() and
                    err.error.get_path().error.is_insufficient_space()):
                print("DROPBOX ERROR: Cannot back up; insufficient space")
            elif err.user_message_text:
                print(err.user_message_text)
            else:
                print(err)



def force_load_from_file(file_name):
  remote_origin = False
  try:
    dbx.files_restore("/cozybot_list/"+file_name, None)
    dbx.files_download_to_file(file_name, "/cozybot_list/"+file_name, None)

    remote_origin = True
  except Exception, e:
    pprint(e)
    if os.path.exists(file_name):
      os.remove(file_name)
    pass

  if os.path.exists(file_name):
    try:
      dump_file = open(file_name, 'rb')
      obj = pickle.load(dump_file)
      dump_file.close()
      return obj
    except:
      if remote_origin:
        if os.path.exists(file_name):
          os.remove(file_name)
        return {}        


def select_revision():
  revisions = sorted(dbx.files_list_revisions("/cozybot_list/"+PERSISTENT_FILE, limit=10).entries,
                     key=lambda entry: entry.server_modified)

  return revisions[0].rev

def load_from_file(file_name):
  remote_origin = False
  if os.path.exists(file_name)==False:
    try:
      rev = select_revision()
      dbx.files_restore("/cozybot_list/"+file_name, rev)
      dbx.files_download_to_file(file_name, "/cozybot_list/"+file_name, rev)

      remote_origin = True
    except Exception, e:
      pprint(e)
      if os.path.exists(file_name):
        os.remove(file_name)
      pass

  if os.path.exists(file_name):
    try:
      dump_file = open(file_name, 'rb')
      obj = pickle.load(dump_file)
      dump_file.close()
      return obj
    except:
      if remote_origin:
        if os.path.exists(file_name):
          os.remove(file_name)
        return {}        
  else:
    return {}


def on_chat_message(msg):
    global vector_dict
    global admin_is_editing
    global admin_is_editing_group
    global group_being_moderated
    global ptime

    content_type, chat_type, chat_id = telepot.glance(msg)
    try:
      user_name = msg['from']['username']
    except:
      user_name = ''
    user_id = msg['from']['id']
    #DEBUG: user_id = msg['message_id']
    if debug:
      pprint(msg)

    #chat_id =-1001054446244 #Chat Id  of the freedompop group

    if content_type == 'text':
      command = msg['text']

      if len(vector_dict)==0:
        vector_dict=load_from_file(PERSISTENT_FILE)

      if user_id in vector_dict:
        vector_dict[user_id]["timestamp"] = datetime.datetime.now()


      if chat_id == group_membership :
        ###### 
        ## Group help
        ######        
        if (command == '/ayuda' or command == '/ayuda'+name_bot or command == '/help' or command == '/help'+name_bot):
          bot.sendMessage(chat_id,
             ghelp_msg,
             reply_to_message_id=msg['message_id']) 
        ###### 
        ## Show id
        ######
        elif (command == '/lista' or command == '/lista'+name_bot):  
          if user_id in admin_list:
            print_list_of_emails(group_membership, msg, vector_dict, bot, True)
        return
 
      if debug == False:
        try:
          mc = bot.getChatMember(group_membership, user_id)
        except:
          return

        if mc['status']!="creator" and mc['status']!="administrator" and mc['status']!="member":
          bot.sendMessage(chat_id, u'No te reconozco y soy algo tímido con desconocidos... 😕', reply_to_message_id=msg['message_id'], disable_notification=True)
          return


      ###### 
      ## Show all
      ######
      if (command == '/estadisticas' or command == '/estadisticas'+name_bot):
          total_mails = 0
          for user in vector_dict:
            total_mails = total_mails + len(vector_dict[user]["mail"])

          bot.sendMessage(chat_id, 'En este momento cuento con '+str(len(vector_dict))+' miembro(s) y un total de '+str(total_mails)+' email(s)' , reply_to_message_id=msg['message_id'], disable_notification=True)


      elif command.startswith('/entrar') or command.startswith('/entrar'+name_bot):
          #pprint(msg)
          prepend=''
          words = command.split()
          if len(words)!=2:
            bot.sendMessage(chat_id, 'No has acertado con el comando. Recuerda que puedes revisar la ayuda (/ayuda'+name_bot+') en cualquier momento.\n\nPara que el comando /entrar'+name_bot+' funcione debes indicarme que mail quieres incorporar a tu nombre.\n\n Ejemplo:\n/entrar'+name_bot+' pepito@mail.com', reply_to_message_id=msg['message_id'], disable_notification=True)
          else:
            emails = words[1].split(',')
            succed_emails = False
            for email in emails:
              if not re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.(?:es|com|edu|gov|int|mil|net|org)$", email):
                bot.sendMessage(chat_id,'No me creo que '+email+' sea un email valido -.-', reply_to_message_id=msg['message_id'], disable_notification=True)
              else:
                if not user_id in vector_dict.keys(): #El usuario no se ha registrado antes
                  vector_dict[user_id] = {"timestamp":datetime.datetime.now(),"mail":set()}
                vector_dict[user_id]["mail"].add(email)
                succed_emails = True
            
            if succed_emails:                
              prepend='El usuario '+user_name+' se ha incluido en la lista de referidos de FreedomPop. Con esta operacion ya ha registrado '+ str(len(vector_dict[user_id]["mail"])) + ' email(s). '
              dump_to_file(vector_dict, PERSISTENT_FILE)
              bot.sendMessage(chat_id, prepend, reply_to_message_id=msg['message_id'], disable_notification=True)


      ###### 
      ## Remove mail
      ######
      elif (command.startswith('/borrar') or command.startswith('/borrar'+name_bot)):
          prepend=''          
          words = command.split()
        
          if len(words)!=2:
            bot.sendMessage(chat_id, 'No has acertado con el comando. Recuerda que puedes revisar la ayuda (/ayuda'+name_bot+') en cualquier momento.\n\nPara que el comando /borrar'+name_bot+' funcione debes indicarme que mail quieres incorporar a tu nombre.\n\n Ejemplo:\n/borrar'+name_bot+' pepito@mail.com', reply_to_message_id=msg['message_id'], disable_notification=True)
          else:
            emails = words[1].split(',')
            succed_emails = False
            for email in emails:
              if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                bot.sendMessage(chat_id,'No me creo que '+email+' sea un email valido -.-', reply_to_message_id=msg['message_id'], disable_notification=True)
              else:
                if user_id in admin_list:
                  remove = []
                  for user in vector_dict:
                    if email in vector_dict[user]["mail"]:
                      vector_dict[user]["mail"].remove(email)
                      prepend='El admin ha modificado la lista de emails. '
                      succed_emails = True

                    if len(vector_dict[user]["mail"]) == 0:
                      remove.append(user)
                  for user in remove:
                    vector_dict.pop(user, None)    

                else:
                  if user_id in vector_dict.keys() and email in vector_dict[user_id]["mail"]: #El usuario no se ha registrado antes
                    vector_dict[user_id]["mail"].remove(email)
                    succed_emails = True
                  if len(vector_dict[user_id]["mail"]) == 0:
                    vector_dict.pop(user_id, None)
                  
            if succed_emails:
              if user_id in vector_dict.keys():
                prepend='El usuario '+user_name+' ha modificado sus emails en la lista. Con esta operacion ya ha registrado '+ str(len(vector_dict[user_id]["mail"])) + ' email(s). '
              else:
                prepend='El usuario '+user_name+' ha modificado sus emails en la lista. Con esta operacion ya ha eliminado todos sus email(s).'
              dump_to_file(vector_dict, PERSISTENT_FILE)
              bot.sendMessage(chat_id, prepend, reply_to_message_id=msg['message_id'], disable_notification=True)
      ###### 
      ## Print my emails
      ######
      elif (command.startswith('/personal') or command.startswith('/personal'+name_bot)):
          text = u"No tengo datos tuyos aún"
          if user_id in vector_dict.keys():
            text = ','.join(vector_dict[user_id]["mail"])

          bot.sendMessage(chat_id,text, reply_to_message_id=msg['message_id'], disable_notification=True)
           

      ###### 
      ## Remove user
      ######                           
      elif (command == '/adios' or command == '/adios'+name_bot): 
          prepend=''                  
          if user_id in vector_dict.keys(): 
            vector_dict.pop(user_id, None)    

          prepend='El usuario '+user_name+' se ha borrado la lista. '

          dump_to_file(vector_dict, PERSISTENT_FILE)
          bot.sendMessage(chat_id, prepend, reply_to_message_id=msg['message_id'], disable_notification=True)

      ###### 
      ## Remove user
      ######                           
      elif (command == '/lista' or command == '/lista'+name_bot): 
    		print_list_of_emails(chat_id, msg, vector_dict, bot) 
      ###### 
      ## Expire by time
      ######      		
      elif (command == '/purga' or command == '/purga'+name_bot):
            if user_id in admin_list:
				ctime = datetime.datetime.now()
				threshold_time = ctime-datetime.timedelta(days=INACTIVE_USER_DAYS)
				remove_inactive_users(vector_dict, threshold_time)
				dump_to_file(vector_dict, PERSISTENT_FILE)
				ptime = ctime
				bot.sendMessage(chat_id, u'He realizado limpieza de todos aquellos emails más antiguos de '+str(ctime-datetime.timedelta(days=INACTIVE_USER_DAYS)), reply_to_message_id=msg['message_id'], disable_notification=True)

      ###### 
      ## Help
      ######                     
      elif (command == '/ayuda' or command == '/ayuda'+name_bot or command == '/help' or command == '/help'+name_bot):
          bot.sendMessage(chat_id,
			       help_msg,
             reply_to_message_id=msg['message_id'])
      ###### 
      ## Administration
      ######   
      elif user_id in creator_list:
                  
        if command == '/dashboard' or command == '/dashboard'+name_bot: 
          show_keyboard = {'keyboard': [['Print', 'Edit'], ['Statistics', 'Return']]}
          bot.sendMessage(chat_id, u'¿Qué hacemos?', reply_markup=show_keyboard)
          admin_is_editing_group=True
        elif (admin_is_editing_group):
            if command == 'Print':
                list_of_chains = []
                email_chain = ''

                for user in vector_dict:
                  if len(vector_dict[user]["mail"]) >=1:
                    string_to_insert = ','.join(vector_dict[user]["mail"])

                    if(len(email_chain)+len(string_to_insert)+1) >= MESSAGE_WIDTH:
                      list_of_chains.append(email_chain)
                      email_chain = ''

                    if len(email_chain):
                      email_chain=email_chain+','+string_to_insert
                    else:
                      email_chain=string_to_insert
               
                if len(email_chain):
                  list_of_chains.append(email_chain)
                              
                for chain in list_of_chains:             
                  bot.sendMessage(chat_id, chain)           
                   
            elif command == 'Edit':
                admin_is_editing_group=False
                group_being_moderated=True
                show_keyboard = {'keyboard': [['Force load from dropbox', 'Force dump to dropbox'],['Remove the emails', 'Return']]}
                bot.sendMessage(chat_id, u'Vamos a editar '+str(group_membership), reply_markup=show_keyboard)
            elif command == 'Statistics':
                total_mails = 0
                for user in vector_dict:
                  total_mails = total_mails + len(vector_dict[user]["mail"])

                bot.sendMessage(chat_id, 'En este momento cuenta con '+str(len(vector_dict))+' miembro(s) y un total de '+str(total_mails)+' email(s)')

            elif command == 'Return':
              hide_keyboard = {'hide_keyboard': True}
              bot.sendMessage(chat_id, u'Listo', reply_markup=hide_keyboard)
              admin_is_editing_group=True
        elif group_being_moderated:
          if command=='Force load from dropbox':
            vector_dict = force_load_from_file(PERSISTENT_FILE)
          elif command=='Force dump to dropbox':
            force_dump_to_file(vector_dict, PERSISTENT_FILE)
          elif command=='Remove the emails':
            for user in vector_dict:
              vector_dict[user]["mail"] = set()
            dump_to_file(vector_dict, PERSISTENT_FILE)
          elif command=='Return':
            show_keyboard = {'keyboard': [['Print', 'Edit'], ['Statistics', 'Return']]}
            bot.sendMessage(chat_id, u'¿Qué hacemos?', reply_markup=show_keyboard)   
            admin_is_editing_group=True
            group_being_moderated=False
        elif debug==True:
          print 'Unexpected command'

      else:
        if debug==True:
          print 'Unexpected command'


if (len(token_dropbox) == 0):
  sys.exit("ERROR: Looks like you didn't add your access token.")

# Create an instance of a Dropbox class, which can make requests to the API.
print("Creating a Dropbox object...")
dbx = dropbox.Dropbox(token_dropbox)

# Check that the access token is valid
try:
  dbx.users_get_current_account()
except AuthError as err:
  sys.exit("ERROR: Invalid access token; try re-generating an access token from the app console on the web.")

bot = telepot.Bot(TOKEN)
bot.message_loop({'chat': on_chat_message})
print('Listening ...')


while 1:
  try: # Do not die...
    time.sleep(INACTIVE_TIME)

    ctime = datetime.datetime.now()

    if (ptime + datetime.timedelta(days=DAYS_BETWEEN_PURGE))<ctime:
      threshold_time = ctime-datetime.timedelta(days=INACTIVE_USER_DAYS)
      remove_inactive_users(vector_dict, threshold_time)
      dump_to_file(vector_dict, PERSISTENT_FILE)
  except:
    time.sleep(INACTIVE_TIME)   