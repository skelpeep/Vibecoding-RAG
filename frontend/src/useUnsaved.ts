import { onBeforeUnmount, onMounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
export function useUnsaved(dirty:()=>boolean,busy:()=>boolean=()=>false){
 async function confirmLeave(){if(busy())return false;if(!dirty())return true;try{await ElMessageBox.confirm('离开后，尚未保存的修改将丢失。','离开当前页面？',{confirmButtonText:'放弃修改并离开',cancelButtonText:'继续编辑'});return true}catch{return false}}
 onBeforeRouteLeave(to=>['/login','/forbidden'].includes(to.path)?true:confirmLeave())
 const unload=(e:BeforeUnloadEvent)=>{if(dirty()||busy()){e.preventDefault();e.returnValue=''}}
 onMounted(()=>window.addEventListener('beforeunload',unload));onBeforeUnmount(()=>window.removeEventListener('beforeunload',unload))
 return {confirmLeave}
}
